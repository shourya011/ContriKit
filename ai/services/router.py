"""LLM router: the only place that talks to providers.

Callers (views, services, future features) use `LLMRouter.chat()` — never a
provider class directly. The router now provides:

    - Priority ordering (ProviderConfig.priority; lower = tried first)
    - Automatic fallback when a provider fails
    - Retry with exponential backoff for transient failures
    - Per-provider rate-limit tracking (ProviderConfig.rate_limit_per_minute)
    - A per-provider circuit breaker (consecutive failures open the breaker)

The design stays list-based: adding providers or changing policies never
touches the service layer, views, or the frontend.
"""

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

from .exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderError,
    LLMProviderServerError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from .providers.base import LLMProvider
from .types import ChatRequest, ChatResponse

# Failures worth retrying on the same provider (transient by nature).
RETRYABLE_ERRORS = (
    LLMTimeoutError,
    LLMRateLimitError,
    LLMProviderServerError,
    LLMProviderUnavailableError,
)

# Failures that should fail over to the next provider but not be retried
# heavily: authentication problems indicate misconfiguration.
FAILOVER_ERRORS = RETRYABLE_ERRORS + (LLMAuthenticationError,)

MAX_BACKOFF_SECONDS = 5.0


@dataclass
class _ProviderState:
    """Runtime state per registered provider (in-process, thread-safe via lock)."""

    consecutive_failures: int = 0
    open_until: float = 0.0
    recent_attempts: list[float] = field(default_factory=list)


class LLMRouter:
    """Routes ChatRequests across configured LLM providers with failover."""

    def __init__(
        self,
        providers: Optional[list[LLMProvider]] = None,
        *,
        fallback: bool = True,
        retries: int = 1,
        retry_backoff: float = 0.5,
        circuit_breaker: bool = True,
        circuit_failure_threshold: int = 3,
        circuit_reset_seconds: int = 60,
    ):
        self._providers: list[LLMProvider] = []
        self._states: dict[str, _ProviderState] = {}
        self._lock = Lock()

        self.fallback = fallback
        self.retries = max(0, int(retries))
        self.retry_backoff = max(0.0, float(retry_backoff))
        self.circuit_breaker = circuit_breaker
        self.circuit_failure_threshold = max(1, int(circuit_failure_threshold))
        self.circuit_reset_seconds = max(0, int(circuit_reset_seconds))

        if providers:
            self.register_many(providers)

    # ── Registration ────────────────────────────────────────────────────────

    def register(self, provider: LLMProvider) -> None:
        if not isinstance(provider, LLMProvider):
            raise TypeError("router.register() expects an LLMProvider instance.")
        with self._lock:
            self._providers.append(provider)
            self._states.setdefault(provider.name, _ProviderState())

    def register_many(self, providers) -> None:
        for provider in providers:
            self.register(provider)

    @property
    def providers(self) -> tuple[LLMProvider, ...]:
        return tuple(self._providers)

    # ── Public API ──────────────────────────────────────────────────────────

    def chat(self, request: ChatRequest) -> ChatResponse:
        """Send a normalized request to the best available provider.

        Raises the most concrete failure: the original provider error when
        every provider fails, or ``LLMConfigurationError`` when no provider
        has credentials at all.
        """
        last_error: Optional[Exception] = None
        attempts = 0

        for provider in self._ordered_providers():
            if not provider.is_configured():
                continue

            state = self._states.setdefault(provider.name, _ProviderState())
            if self._is_blocked(provider, state):
                reason = self._block_reason(provider, state)
                last_error = LLMProviderUnavailableError(
                    f"Provider '{provider.name}' is skipped ({reason})."
                )
                continue

            attempts += 1
            self._record_attempt(state)
            try:
                response = self._with_retries(provider, request)
                self._record_success(state)
                return response
            except FAILOVER_ERRORS as exc:
                self._record_failure(state)
                last_error = exc
                # Authentication errors indicate a misconfigured key; falling
                # back is still better than failing the whole request.
                if not self.fallback:
                    raise exc
                continue
            except LLMProviderError as exc:
                # Deterministic client errors (e.g. bad 4xx request) are not
                # retried and not worth failing over on.
                raise exc

        if last_error is not None:
            # Preserve the concrete failure (auth error, timeout, rate limit,
            # unreachable provider, ...) so callers/views can report the real
            # cause instead of a generic "AI is not configured" message.
            raise last_error

        raise LLMConfigurationError(
            "No LLM provider is configured. Set AI_GROQ_API_KEY in your "
            "environment (.env file) and try again."
        )

    def health(self) -> list[dict]:
        """Status of every registered provider (no API calls, no secrets)."""
        result = []
        for provider in self._ordered_providers():
            state = self._states.setdefault(provider.name, _ProviderState())
            result.append(
                {
                    **provider.health(),
                    "priority": provider.config.priority,
                    "rate_limit_per_minute": provider.config.rate_limit_per_minute,
                    "status": self._status_label(provider, state),
                }
            )
        return result

    # ── Provider selection / ordering ──────────────────────────────────────

    def _ordered_providers(self) -> list[LLMProvider]:
        """Providers sorted by priority (lower number = higher priority)."""
        return sorted(self._providers, key=lambda p: (p.config.priority, p.name))

    def _select_provider(self) -> LLMProvider:
        """First configured, unblocked provider (kept for callers/tests)."""
        for provider in self._ordered_providers():
            if not provider.is_configured():
                continue
            state = self._states.setdefault(provider.name, _ProviderState())
            if not self._is_blocked(provider, state):
                return provider
        raise LLMProviderUnavailableError(
            "No LLM provider is available. Check API keys and provider health."
        )

    # ── Retry with exponential backoff ─────────────────────────────────────

    def _with_retries(self, provider: LLMProvider, request: ChatRequest) -> ChatResponse:
        attempts = self.retries + 1
        last_exc = None
        for attempt in range(attempts):
            try:
                return provider.chat(request)
            except LLMAuthenticationError:
                # Wrong credentials: no point retrying the same provider.
                raise
            except LLMConfigurationError:
                raise
            except RETRYABLE_ERRORS as exc:
                # Transient: timeout / rate limit / 5xx / unreachable.
                last_exc = exc
                if attempt < attempts - 1:
                    delay = min(
                        self.retry_backoff * (2 ** attempt), MAX_BACKOFF_SECONDS
                    )
                    if delay:
                        time.sleep(delay)
                continue
            except LLMProviderError as exc:
                # Deterministic client error (bad request, 4xx): don't retry.
                raise exc
        raise last_exc  # always set when the loop exhausts

    # ── Circuit breaker / rate limiting ────────────────────────────────────

    def _is_blocked(self, provider: LLMProvider, state: _ProviderState) -> bool:
        return bool(self._block_reason(provider, state))

    def _block_reason(self, provider: LLMProvider, state: _ProviderState) -> str:
        if self.circuit_breaker and self._breaker_is_open(state):
            return "circuit breaker is open"
        if self._is_rate_limited(provider, state):
            return "rate limit reached"
        return ""

    def _breaker_is_open(self, state: _ProviderState) -> bool:
        with self._lock:
            if state.open_until:
                if time.time() >= state.open_until:
                    # Circuit half-opens after the reset window.
                    state.open_until = 0.0
                    state.consecutive_failures = 0
                    return False
                return True
        return False

    def _is_rate_limited(self, provider: LLMProvider, state: _ProviderState) -> bool:
        limit = provider.config.rate_limit_per_minute
        if not limit:
            return False
        now = time.time()
        with self._lock:
            window = [t for t in state.recent_attempts if now - t < 60]
            state.recent_attempts = window
            return len(window) >= limit

    def _record_attempt(self, state: _ProviderState) -> None:
        with self._lock:
            now = time.time()
            state.recent_attempts.append(now)
            state.recent_attempts = [t for t in state.recent_attempts if now - t < 60]

    def _record_success(self, state: _ProviderState) -> None:
        with self._lock:
            state.consecutive_failures = 0
            state.open_until = 0.0

    def _record_failure(self, state: _ProviderState) -> None:
        with self._lock:
            state.consecutive_failures += 1
            if state.consecutive_failures >= self.circuit_failure_threshold:
                state.open_until = time.time() + self.circuit_reset_seconds

    def _status_label(self, provider: LLMProvider, state: _ProviderState) -> str:
        if not provider.is_configured():
            return "not_configured"
        if self.circuit_breaker and self._breaker_is_open(state):
            return "circuit_open"
        if self._is_rate_limited(provider, state):
            return "rate_limited"
        return "healthy"
