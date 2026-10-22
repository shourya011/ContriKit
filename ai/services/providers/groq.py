"""Groq Chat Completions provider.

Talks to Groq's Chat Completions endpoint:

    POST {base_url}/chat/completions
    Authorization: Bearer <AI_GROQ_API_KEY>

Default endpoint is ``https://api.groq.com/openai/v1`` (Groq's documented
Chat Completions URL) with ``openai/gpt-oss-120b``. Using plain
``requests`` keeps the provider dependency-free: ``requests`` is already a
project dependency (GitHub API), so no extra package is required and the
code stays portable to PythonAnywhere.

Supports Groq function calling; tool *execution* happens in the service
layer, never here.
"""

import json
import logging
import time

import requests

from ..exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMProviderServerError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from ..types import ChatRequest, ChatResponse, ToolCall, UsageStats
from .base import LLMProvider

logger = logging.getLogger(__name__)

GROQ_KEY_HINT = "AI_GROQ_API_KEY"

# Groq's gpt-oss models accept these OpenAI-compatible reasoning controls.
# Keep the list small and explicit: sending them to a model that does not
# support them is a 400, so the provider only sends them for gpt-oss.
REASONING_MODEL_PREFIXES = ("openai/gpt-oss-",)
REASONING_EFFORTS = ("low", "medium", "high")


class GroqProvider(LLMProvider):
    """Chat Completions provider for Groq."""

    name = "groq"
    display_name = "Groq"

    def is_configured(self) -> bool:
        # Trim whitespace/newlines: a key pasted into .env with a trailing
        # space is still the same key, but requests would send the space too.
        return bool((self.config.api_key or "").strip())

    def chat(self, request: ChatRequest) -> ChatResponse:
        if not self.is_configured():
            raise LLMConfigurationError(
                f"Provider '{self.name}' is not configured (missing API key)."
            )

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        payload = self._build_payload(request)
        headers = {
            "Authorization": f"Bearer {self.config.api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ContribKit-AI/1.0",
        }
        timeout = self._effective_timeout(request)

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout as exc:
            raise LLMTimeoutError(
                f"Provider '{self.name}' timed out after {timeout:g}s.",
                provider=self.name,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise LLMProviderUnavailableError(
                f"Provider '{self.name}' is unreachable: {exc}",
            ) from exc

        self._raise_for_status(response)
        return self._parse_response(response)

    # ── Internals ──────────────────────────────────────────────────────────

    def _effective_timeout(self, request: ChatRequest) -> float:
        """Socket timeout, clamped to the request's remaining time budget."""
        timeout = float(request.timeout or self.config.timeout or 60)
        if request.deadline is not None:
            remaining = request.deadline - time.monotonic()
            if remaining <= 0:
                raise LLMTimeoutError(
                    f"Provider '{self.name}' was not called: the request's "
                    "time budget is exhausted.",
                    provider=self.name,
                )
            timeout = max(1.0, min(timeout, remaining))
        return timeout

    def _build_payload(self, request: ChatRequest) -> dict:
        model = request.model or self.config.model
        payload = {
            "model": model,
            "messages": [self._serialize_message(message) for message in request.messages],
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        elif self.config.temperature is not None:
            payload["temperature"] = self.config.temperature

        # Groq deprecated ``max_tokens`` in favour of ``max_completion_tokens``
        # (which also covers reasoning tokens on gpt-oss models).
        max_tokens = request.max_tokens if request.max_tokens is not None else self.config.max_tokens
        if max_tokens:
            payload["max_completion_tokens"] = max_tokens

        if self._supports_reasoning_controls(model):
            effort = (self.config.reasoning_effort or "").strip().lower()
            if effort in REASONING_EFFORTS:
                payload["reasoning_effort"] = effort
            # The widget never shows chain-of-thought; skipping the
            # ``reasoning`` field keeps responses (and latency) smaller.
            payload["include_reasoning"] = False

        if request.tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    },
                }
                for tool in request.tools
            ]
        return payload

    @staticmethod
    def _supports_reasoning_controls(model: str) -> bool:
        return any(str(model or "").startswith(prefix) for prefix in REASONING_MODEL_PREFIXES)

    @staticmethod
    def _serialize_message(message) -> dict:
        serialized = {"role": message.role, "content": message.content}
        if message.tool_calls:
            serialized["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        if message.tool_call_id:
            serialized["tool_call_id"] = message.tool_call_id
        return serialized

    def _raise_for_status(self, response: requests.Response) -> None:
        status = response.status_code
        provider = self.name
        error = self._error_details(response)
        code = error.get("code", "")
        message = error.get("message", "")

        if status in (401, 403) or code in ("invalid_api_key", "authentication_error"):
            raise LLMAuthenticationError(
                f"Provider '{provider}' rejected the API key (HTTP {status}). "
                f"Check {GROQ_KEY_HINT}.",
                status_code=status,
                provider=provider,
            )
        if status == 429 or code in (
            "rate_limit_exceeded",
            "tokens_rate_limit_exceeded",
            "requests_rate_limit_exceeded",
        ):
            raise LLMRateLimitError(
                f"Provider '{provider}' rate limit hit (HTTP {status}). Try again later.",
                status_code=status,
                provider=provider,
            )
        if code in ("decommissioned_model", "model_decommissioned") or (
            code == "model_not_found"
        ):
            raise LLMProviderError(
                f"Provider '{provider}' does not serve model "
                f"'{self.config.model}' (HTTP {status}). Update AI_GROQ_MODEL.",
                status_code=status,
                provider=provider,
                code=code,
            )
        if status >= 500:
            raise LLMProviderServerError(
                f"Provider '{provider}' server error (HTTP {status}).",
                status_code=status,
                provider=provider,
                code=code,
            )
        if status >= 400:
            # Keep the provider's message in the log-facing exception, but
            # never echo the full response body (it can contain request data).
            detail = f": {message[:200]}" if message else ""
            raise LLMProviderError(
                f"Provider '{provider}' request failed (HTTP {status}){detail}",
                status_code=status,
                provider=provider,
                code=code,
            )

    @staticmethod
    def _error_details(response: requests.Response) -> dict:
        """Extract Groq's structured error code/message, if present."""
        try:
            data = response.json()
        except ValueError:
            return {}
        if not isinstance(data, dict):
            return {}
        error = data.get("error")
        if not isinstance(error, dict):
            return {}
        return {
            "code": str(error.get("code") or error.get("type") or ""),
            "message": str(error.get("message") or ""),
        }

    def _parse_response(self, response: requests.Response) -> ChatResponse:
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMInvalidResponseError(
                f"Provider '{self.name}' returned a non-JSON response."
            ) from exc

        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMInvalidResponseError(
                f"Provider '{self.name}' returned an unexpected payload shape."
            ) from exc

        content = message.get("content") or ""
        tool_calls = self._parse_tool_calls(message.get("tool_calls") or [])
        finish_reason = str(
            data.get("choices", [{}])[0].get("finish_reason") or "stop"
        )

        if not content.strip() and not tool_calls:
            if finish_reason == "length":
                raise LLMInvalidResponseError(
                    f"Provider '{self.name}' ran out of completion tokens "
                    "(reasoning uses part of the budget). Raise "
                    "AI_GROQ_MAX_TOKENS and try again."
                )
            raise LLMInvalidResponseError(
                f"Provider '{self.name}' returned empty content with no tool calls."
            )

        usage = UsageStats.from_mapping(data.get("usage"))
        logger.info(
            "LLM response received from %s (model=%s, total_tokens=%s, "
            "tool_calls=%d, finish_reason=%s)",
            self.name,
            data.get("model") or self.config.model,
            usage.total_tokens if usage else "unknown",
            len(tool_calls),
            finish_reason,
        )
        return ChatResponse(
            content=content.strip(),
            provider=self.name,
            model=data.get("model") or self.config.model,
            usage=usage,
            # Never keep the raw payload around in the response object: it may
            # contain provider internals (reasoning, echoed request data).
            raw=None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )

    @staticmethod
    def _parse_tool_calls(raw_calls: list) -> tuple[ToolCall, ...]:
        calls = []
        for raw in raw_calls:
            if not isinstance(raw, dict):
                continue
            function = raw.get("function") or {}
            arguments_raw = function.get("arguments") or "{}"
            try:
                arguments = json.loads(arguments_raw) if arguments_raw else {}
                if not isinstance(arguments, dict):
                    arguments = {}
            except (ValueError, TypeError):
                # Keep malformed arguments visible so the service layer can
                # return a controlled error to the model instead of dropping
                # the call silently.
                arguments = {"_malformed": arguments_raw}
            calls.append(
                ToolCall(
                    id=str(raw.get("id") or ""),
                    name=str(function.get("name") or ""),
                    arguments=arguments,
                )
            )
        return tuple(calls)
