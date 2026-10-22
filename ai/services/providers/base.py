"""Provider abstraction: every LLM backend implements `LLMProvider`."""

from abc import ABC, abstractmethod

from ..types import ChatRequest, ChatResponse, ProviderConfig


class LLMProvider(ABC):
    """Abstract contract every LLM provider implements.

    The rest of the application only knows this interface (via the router),
    so adding a new provider never touches views, settings consumers, or the
    request/response types.
    """

    name = "base"
    display_name = "Base Provider"

    def __init__(self, config: ProviderConfig):
        if not isinstance(config, ProviderConfig):
            raise TypeError("Provider configuration must be a ProviderConfig instance.")
        self.config = config
        if config.name:
            self.name = config.name

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether this provider can serve requests (e.g. API key present)."""

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """Send a normalized ChatRequest and return a normalized ChatResponse."""

    def health(self) -> dict:
        """Lightweight status used by diagnostics — never contacts the API."""
        return {
            "provider": self.name,
            "configured": self.is_configured(),
            "model": self.config.model,
        }

    # ── Reserved extension points (added in later steps) ──────────────────
    # - health_check(): live ping used by circuit breaker / health routing.
    # - rate_limit window tracking (ProviderConfig.rate_limit_per_minute).
    # - retry/backoff policy and idempotency support for safe retries.
