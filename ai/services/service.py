"""Public AI service gateway.

This is the single entry point the rest of ContribKit calls to get an LLM
response:

    user message / feature
        → AIService.chat(messages, tools=..., user=..., page_path=...)
        → LLMRouter
        → LLMProvider
        → (tool calls executed via ToolRegistry, looped)
        → ChatResponse

Providers/keys live server-side only; nothing is ever passed to templates or
JavaScript. Views stay thin and provider-agnostic.

When a ToolRegistry is supplied, the service runs the provider's native tool
loop: the LLM may call registered tools (search_issues, get_template, ...),
results are fed back as real data, and the loop terminates with a final
text answer. Tool execution never raises into the caller.
"""

import json
import logging
import re
import time

from django.conf import settings

from .exceptions import AIServiceError, LLMConfigurationError, LLMProviderError
from .prompts import build_system_prompt
from .providers import PROVIDER_REGISTRY, get_provider_class, get_provider_defaults
from .router import LLMRouter
from .tools import ToolContext, ToolRegistry, build_default_tool_registry
from .types import (
    GROQ_RETIRED_MODELS,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ProviderConfig,
)

logger = logging.getLogger(__name__)

# Module-level cache: the router is built once per process from settings.
# The cache key makes the service rebuild when settings change (tests with
# ``override_settings``, or a management command after a reload).
_ai_service: "AIService | None" = None
_ai_service_key = None

# Settings that determine the provider/router wiring.
CACHE_SETTINGS = (
    "AI_PROVIDERS",
    "AI_PROVIDER",
    "AI_GROQ_API_KEY",
    "AI_GROQ_BASE_URL",
    "AI_GROQ_MODEL",
    "AI_GROQ_TIMEOUT",
    "AI_GROQ_MAX_TOKENS",
    "AI_GROQ_TEMPERATURE",
    "AI_GROQ_REASONING_EFFORT",
    "AI_GROQ_PRIORITY",
    "AI_GROQ_RATE_LIMIT",
    "AI_PROVIDER_FALLBACK",
    "AI_PROVIDER_RETRIES",
    "AI_PROVIDER_RETRY_BACKOFF",
    "AI_PROVIDER_CIRCUIT_BREAKER",
    "AI_PROVIDER_CIRCUIT_FAILURE_THRESHOLD",
    "AI_PROVIDER_CIRCUIT_RESET_SECONDS",
)

MAX_TOOL_ROUNDS = 4
# One user turn (including retries + tool rounds) must finish well inside
# PythonAnywhere's default 300s WSGI request budget.
MAX_REQUEST_SECONDS = 55
ISSUE_PATH_RE = re.compile(r"^/issues/(?P<issue_id>\d+)/")

# Settings key used for Groq's API key. Other vendor names are not supported.
PROVIDER_KEY_SETTINGS = {
    "groq": "AI_GROQ_API_KEY",
}

PROVIDER_DEFAULT_PRIORITY = {
    "groq": 10,
}


class AIService:
    """Provider-agnostic AI facade used by the rest of the application."""

    def __init__(self, router: LLMRouter | None = None, tools: ToolRegistry | None = None):
        self.router = router or LLMRouter()
        self.tools = tools

    def chat(
        self,
        messages,
        *,
        model=None,
        temperature=None,
        max_tokens=None,
        timeout=None,
        tools: ToolRegistry | None = None,
        user=None,
        page_path=None,
        issue_id=None,
        max_tool_rounds: int = MAX_TOOL_ROUNDS,
        tool_events: list | None = None,
    ) -> ChatResponse:
        """Send messages through the LLM router, executing tools when asked.

        ``tools`` (a ToolRegistry) enables the tool loop; ``user``/``page_path``/
        ``issue_id`` build the server-controlled ToolContext tools receive.
        ``tool_events`` (an optional list) receives ``{"name", "arguments",
        "result"}`` for every executed tool so callers can build UI source
        links without re-running tools or re-querying the database.
        """
        self._validate_messages(messages)
        registry = tools if tools is not None else self.tools
        issue_id = issue_id or _issue_id_from_path(page_path)
        context = ToolContext(user=user, page_path=page_path, issue_id=issue_id)
        working = list(messages)
        specs = registry.specs() if registry else ()
        deadline = time.monotonic() + MAX_REQUEST_SECONDS

        rounds = max_tool_rounds if registry else 1
        for _ in range(rounds):
            request = self._build_request(
                working, specs, model=model, temperature=temperature,
                max_tokens=max_tokens, timeout=timeout, deadline=deadline,
            )
            try:
                response = self.router.chat(request)
            except LLMProviderError as exc:
                if not specs or not _is_tool_protocol_error(exc):
                    raise
                # Groq models occasionally emit a malformed tool call
                # (``tool_use_failed``/HTTP 400). The user still deserves an
                # answer, so retry once without tools instead of failing.
                logger.warning(
                    "Provider rejected a tool call (%s); retrying without tools.",
                    exc.code or exc.status_code,
                )
                specs = ()
                request = self._build_request(
                    _without_tool_protocol(working), (), model=model,
                    temperature=temperature, max_tokens=max_tokens,
                    timeout=timeout, deadline=deadline,
                )
                response = self.router.chat(request)
            if not response.tool_calls or not registry:
                return response

            # Ask the provider again with the tool results appended.
            working.append(
                ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for call in response.tool_calls:
                result = registry.execute(call.name, call.arguments, context)
                if tool_events is not None:
                    tool_events.append(
                        {
                            "name": call.name,
                            "arguments": call.arguments,
                            "result": result,
                        }
                    )
                working.append(
                    ChatMessage(
                        role="tool",
                        content=json.dumps(result, ensure_ascii=False, default=str),
                        tool_call_id=call.id,
                    )
                )

        # Safety net: force a final answer without more tool calls. Tool
        # protocol messages are stripped so the provider never sees a
        # ``role="tool"`` turn without a matching ``tools`` schema.
        request = self._build_request(
            _without_tool_protocol(working), (), model=model,
            temperature=temperature, max_tokens=max_tokens,
            timeout=timeout, deadline=deadline,
        )
        return self.router.chat(request)

    def is_configured(self) -> bool:
        """True when at least one registered provider has credentials."""
        return any(provider.is_configured() for provider in self.router.providers)

    def health(self) -> dict:
        """Diagnostics for monitoring/health checks (no secrets, no API call)."""
        from ai.env_diagnostics import env_health_payload

        providers = self.router.health()
        configured = [p["provider"] for p in providers if p.get("configured")]
        active = None
        for provider in self.router.providers:
            if provider.is_configured() and provider.config.rate_limit_per_minute is None:
                active = provider.name
                break
        tools_enabled = self.tools is not None
        return {
            "status": "ok" if configured else "not_configured",
            "service": "contribkit-ai",
            "active_provider": active if active else (configured[0] if configured else None),
            "providers": providers,
            "configuration": env_health_payload(redact_paths=True),
            "tools": {
                "enabled": tools_enabled,
                "count": len(self.tools.names()) if tools_enabled else 0,
                "names": self.tools.names() if tools_enabled else [],
            },
            # Feature flags: what the router currently supports.
            "extensions": {
                "multi_provider_priority": len(self.router.providers) > 1,
                "fallback": self.router.fallback,
                "retry_backoff": self.router.retries > 0,
                "rate_limit_tracking": any(
                    p.config.rate_limit_per_minute for p in self.router.providers
                ),
                "circuit_breaker": self.router.circuit_breaker,
                "priority_queue": False,
                "usage_tracking": True,
            },
        }

    @staticmethod
    def _build_request(
        messages, specs, *, model=None, temperature=None, max_tokens=None,
        timeout=None, deadline=None,
    ) -> ChatRequest:
        return ChatRequest(
            messages=tuple(messages),
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            deadline=deadline,
            tools=tuple(specs),
        )

    @staticmethod
    def _validate_messages(messages) -> None:
        if not messages:
            raise AIServiceError("At least one message is required.")
        for message in messages:
            if not isinstance(message, ChatMessage):
                raise TypeError("messages must be ChatMessage instances.")
            if message.role not in ("system", "user", "assistant", "tool"):
                raise ValueError(f"Unsupported message role: {message.role!r}.")


def _provider_names() -> list[str]:
    """Provider list from settings — Groq is the only supported backend.

    Reads ``AI_PROVIDERS`` / ``AI_PROVIDER`` so leftover multi-vendor env
    values still parse, then keeps only ``groq``. If nothing valid remains
    (empty list, or only openai/gemini/anthropic leftovers), falls back to
    Groq so the chatbot never tries another vendor.
    """
    raw = getattr(settings, "AI_PROVIDERS", "") or getattr(settings, "AI_PROVIDER", "groq")
    names = [name.strip().lower() for name in str(raw).split(",") if name.strip()]
    known = [name for name in names if name in PROVIDER_REGISTRY]
    return known or ["groq"]


def _provider_setting(name: str, suffix: str, default):
    """Read AI_<NAME>_<SUFFIX> from settings, e.g. AI_GROQ_API_KEY."""
    key = f"AI_{name.replace('-', '_').upper()}_{suffix}"
    value = getattr(settings, key, None)
    return default if value in (None, "") else value


def _is_tool_protocol_error(exc) -> bool:
    """True when the provider rejected the *tool call format*, not the request.

    Groq's gpt-oss models occasionally return a tool call that fails Groq's
    own validator (HTTP 400, ``tool_use_failed``). That is recoverable: the
    same conversation without tools normally produces a plain answer.
    """
    return getattr(exc, "code", None) in {
        "tool_use_failed",
        "tool_call_validation_failed",
        "invalid_tool_call",
    }


def _without_tool_protocol(messages) -> list[ChatMessage]:
    """Drop tool calls/results so a no-tools retry is a valid conversation.

    Sending ``role="tool"`` messages to a request without ``tools`` (or an
    assistant ``tool_calls`` field) is itself rejected by some providers, so
    the fallback keeps only plain user/assistant/system turns.
    """
    cleaned = []
    for message in messages:
        if message.role == "tool":
            continue
        if message.role == "assistant" and message.tool_calls:
            content = (message.content or "").strip()
            if not content:
                continue
            cleaned.append(ChatMessage(role="assistant", content=content))
            continue
        cleaned.append(message)
    return cleaned


def _issue_id_from_path(page_path) -> int | None:
    """Parse ``/issues/<id>/`` so tools know which issue the user is viewing."""
    if not page_path:
        return None
    match = ISSUE_PATH_RE.match(str(page_path))
    if not match:
        return None
    try:
        return int(match.group("issue_id"))
    except (TypeError, ValueError):
        return None


def _provider_config(name: str) -> ProviderConfig:
    """Build a ProviderConfig for one provider from settings/env."""
    defaults = get_provider_defaults(name)
    key_setting = PROVIDER_KEY_SETTINGS.get(name, "")
    api_key = (getattr(settings, key_setting, "") if key_setting else "") or ""
    api_key = str(api_key).strip()
    rate_limit = _provider_setting(name, "RATE_LIMIT", 0)
    model = _provider_setting(name, "MODEL", defaults.get("model"))
    if name == "groq" and model in GROQ_RETIRED_MODELS:
        replacement = GROQ_RETIRED_MODELS[model]
        logger.warning(
            "Groq model %s is retired; using %s. Update AI_GROQ_MODEL.",
            model,
            replacement,
        )
        model = replacement
    timeout = _provider_setting(name, "TIMEOUT", 60)
    # Keep each Groq hop inside PythonAnywhere's request budget.
    try:
        timeout = min(int(timeout), MAX_REQUEST_SECONDS)
    except (TypeError, ValueError):
        timeout = MAX_REQUEST_SECONDS
    reasoning = _provider_setting(name, "REASONING_EFFORT", None)
    if isinstance(reasoning, str):
        reasoning = reasoning.strip().lower() or None
    return ProviderConfig(
        name=name,
        api_key=api_key,
        base_url=_provider_setting(name, "BASE_URL", defaults.get("base_url")),
        model=model,
        timeout=timeout,
        max_tokens=_provider_setting(name, "MAX_TOKENS", 2048),
        temperature=_provider_setting(name, "TEMPERATURE", 0.7),
        reasoning_effort=reasoning,
        priority=_provider_setting(name, "PRIORITY", PROVIDER_DEFAULT_PRIORITY.get(name, 100)),
        rate_limit_per_minute=int(rate_limit) if rate_limit else None,
    )


def build_default_router() -> LLMRouter:
    """Build the router from Django settings with priority/fallback/retries."""
    providers = []
    for name in _provider_names():
        try:
            provider_cls = get_provider_class(name)
        except LLMConfigurationError as exc:
            logger.warning("Skipping unknown AI provider '%s': %s", name, exc)
            continue
        providers.append(provider_cls(_provider_config(name)))

    return LLMRouter(
        providers,
        fallback=getattr(settings, "AI_PROVIDER_FALLBACK", True),
        retries=getattr(settings, "AI_PROVIDER_RETRIES", 2),
        retry_backoff=getattr(settings, "AI_PROVIDER_RETRY_BACKOFF", 0.5),
        circuit_breaker=getattr(settings, "AI_PROVIDER_CIRCUIT_BREAKER", True),
        circuit_failure_threshold=getattr(settings, "AI_PROVIDER_CIRCUIT_FAILURE_THRESHOLD", 3),
        circuit_reset_seconds=getattr(settings, "AI_PROVIDER_CIRCUIT_RESET_SECONDS", 60),
    )


def _service_cache_key():
    return tuple(str(getattr(settings, name, "")) for name in CACHE_SETTINGS)


def reset_ai_service() -> None:
    """Drop the cached service so the next call re-reads configuration."""
    global _ai_service, _ai_service_key
    _ai_service = None
    _ai_service_key = None


def get_ai_service() -> AIService:
    """Return the process-wide AI service (built once per configuration)."""
    global _ai_service, _ai_service_key
    key = _service_cache_key()
    if _ai_service is None or _ai_service_key != key:
        _ai_service = AIService(
            router=build_default_router(),
            tools=build_default_tool_registry(),
        )
        _ai_service_key = key
    return _ai_service


def ai_chat(messages, **kwargs) -> ChatResponse:
    """Convenience function: ai_chat([ChatMessage(...), ...], user=..., ...)."""
    return get_ai_service().chat(messages, **kwargs)


def ai_assistant_chat(
    message: str,
    *,
    user=None,
    page_path=None,
    issue_id=None,
    history: list[ChatMessage] | None = None,
    **kwargs,
) -> ChatResponse:
    """One-turn assistant call: system prompt + user/page context + tools.

    This is what the future chat endpoint will use: it builds the ContribKit
    system prompt, appends any conversation history, adds the user message,
    and lets the model use the controlled tool registry.
    """
    system_prompt = build_system_prompt(user=user, page_path=page_path)
    messages = [ChatMessage(role="system", content=system_prompt)]
    if history:
        messages.extend(history)
    messages.append(ChatMessage(role="user", content=message))
    return get_ai_service().chat(
        messages,
        user=user,
        page_path=page_path,
        issue_id=issue_id,
        **kwargs,
    )
