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


class GroqProvider(LLMProvider):
    """Chat Completions provider for Groq."""

    name = "groq"
    display_name = "Groq"

    def is_configured(self) -> bool:
        return bool(self.config.api_key)

    def chat(self, request: ChatRequest) -> ChatResponse:
        if not self.is_configured():
            raise LLMConfigurationError(
                f"Provider '{self.name}' is not configured (missing API key)."
            )

        url = f"{self.config.base_url.rstrip('/')}/chat/completions"
        payload = self._build_payload(request)
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        timeout = request.timeout or self.config.timeout

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.exceptions.Timeout as exc:
            raise LLMTimeoutError(
                f"Provider '{self.name}' timed out after {timeout}s.",
                provider=self.name,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise LLMProviderUnavailableError(
                f"Provider '{self.name}' is unreachable: {exc}",
            ) from exc

        self._raise_for_status(response)
        return self._parse_response(response)

    # ── Internals ──────────────────────────────────────────────────────────

    def _build_payload(self, request: ChatRequest) -> dict:
        payload = {
            "model": request.model or self.config.model,
            "messages": [self._serialize_message(message) for message in request.messages],
            "stream": False,
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        elif self.config.temperature is not None:
            payload["temperature"] = self.config.temperature

        max_tokens = request.max_tokens if request.max_tokens is not None else self.config.max_tokens
        if max_tokens:
            payload["max_tokens"] = max_tokens

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
        if status in (401, 403):
            raise LLMAuthenticationError(
                f"Provider '{provider}' rejected the API key (HTTP {status}). "
                f"Check {GROQ_KEY_HINT}.",
                status_code=status,
                provider=provider,
            )
        if status == 429:
            raise LLMRateLimitError(
                f"Provider '{provider}' rate limit hit (HTTP 429). Try again later.",
                status_code=status,
                provider=provider,
            )
        if status >= 500:
            raise LLMProviderServerError(
                f"Provider '{provider}' server error (HTTP {status}).",
                status_code=status,
                provider=provider,
            )
        if status >= 400:
            raise LLMProviderError(
                f"Provider '{provider}' request failed (HTTP {status}): "
                f"{response.text[:300]}",
                status_code=status,
                provider=provider,
            )

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

        if not content.strip() and not tool_calls:
            raise LLMInvalidResponseError(
                f"Provider '{self.name}' returned empty content with no tool calls."
            )

        usage = UsageStats.from_mapping(data.get("usage"))
        logger.info(
            "LLM response received from %s (model=%s, total_tokens=%s, tool_calls=%d)",
            self.name,
            data.get("model") or self.config.model,
            usage.total_tokens if usage else "unknown",
            len(tool_calls),
        )
        return ChatResponse(
            content=content.strip(),
            provider=self.name,
            model=data.get("model") or self.config.model,
            usage=usage,
            raw=data,
            tool_calls=tool_calls,
            finish_reason=str(data.get("choices", [{}])[0].get("finish_reason") or "stop"),
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
