"""Provider registry: ContribKit talks to Groq only.

The rest of the application resolves the provider through this module so
views, the router, and settings never hard-code Groq's class. Unknown
names (openai, gemini, anthropic, grok, …) raise ``LLMConfigurationError``.
"""

from ..exceptions import LLMConfigurationError
from ..types import GROQ_DEFAULT_BASE_URL, GROQ_DEFAULT_MODEL
from .base import LLMProvider
from .groq import GroqProvider

PROVIDER_REGISTRY = {
    "groq": GroqProvider,
}

# Vendor defaults; everything is overridable through env/settings.
PROVIDER_DEFAULTS = {
    "groq": {
        "base_url": GROQ_DEFAULT_BASE_URL,
        "model": GROQ_DEFAULT_MODEL,
    },
}


def get_provider_class(name: str) -> type[LLMProvider]:
    """Resolve a provider name (from settings) to a provider class."""
    try:
        return PROVIDER_REGISTRY[name.strip().lower()]
    except KeyError:
        available = ", ".join(sorted(PROVIDER_REGISTRY))
        raise LLMConfigurationError(
            f"Unknown LLM provider '{name}'. Available providers: {available}."
        )


def get_provider_defaults(name: str) -> dict:
    """Per-vendor defaults (base URL / model)."""
    return dict(PROVIDER_DEFAULTS.get(name.strip().lower(), {}))


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(PROVIDER_REGISTRY))


__all__ = [
    "LLMProvider",
    "GroqProvider",
    "PROVIDER_REGISTRY",
    "PROVIDER_DEFAULTS",
    "get_provider_class",
    "get_provider_defaults",
    "available_providers",
]
