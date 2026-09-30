"""Typed exceptions for the AI service layer.

Every failure in the `ai` service surfaces as an `AIServiceError` subclass so
callers (views, management commands, future features) can handle errors
uniformly without knowing provider internals.
"""


class AIServiceError(Exception):
    """Base class for all AI service layer errors."""


class LLMConfigurationError(AIServiceError):
    """The provider is missing/invalid configuration (e.g. no API key)."""


class LLMProviderError(AIServiceError):
    """The provider returned an HTTP error response (request failed)."""

    def __init__(self, message, status_code=None, provider=None):
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


class LLMProviderServerError(LLMProviderError):
    """Provider-side failure (HTTP 5xx) — safe to retry / fail over."""


class LLMTimeoutError(LLMProviderError):
    """The provider did not respond within the configured timeout."""


class LLMAuthenticationError(LLMProviderError):
    """Provider rejected the credentials (401/403) — check the API key."""


class LLMRateLimitError(LLMProviderError):
    """The provider is rate limiting us (HTTP 429)."""


class LLMProviderUnavailableError(AIServiceError):
    """No provider is configured/available to serve a request."""


class LLMInvalidResponseError(AIServiceError):
    """The provider responded with malformed/unexpected content."""
