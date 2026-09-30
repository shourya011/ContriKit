"""Shared data types for the AI service layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# Roles accepted by chat completion APIs.
VALID_ROLES = ("system", "user", "assistant", "tool")

GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
# Groq retired llama-3.3-70b-versatile on 2026-08-16; gpt-oss-120b is the
# documented replacement (tool calling still supported).
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_RETIRED_MODELS = {
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
}


@dataclass(frozen=True)
class ToolSpec:
    """Provider-facing function definition (JSON schema for a controlled tool)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatMessage:
    """One message inside a conversation. Role is system/user/assistant/tool."""

    role: str
    content: str = ""
    # Populated when the assistant requests tool execution.
    tool_calls: tuple[ToolCall, ...] = ()
    # Populated for role="tool" messages that answer a tool call.
    tool_call_id: Optional[str] = None


@dataclass(frozen=True)
class UsageStats:
    """Token usage reported by a provider (when available)."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_mapping(cls, data: Optional[dict]) -> Optional["UsageStats"]:
        """Build UsageStats from a provider payload; returns None if absent."""
        if not data:
            return None
        return cls(
            prompt_tokens=int(data.get("prompt_tokens") or 0),
            completion_tokens=int(data.get("completion_tokens") or 0),
            total_tokens=int(data.get("total_tokens") or 0),
        )


@dataclass(frozen=True)
class ChatRequest:
    """A normalized request the router hands to a provider."""

    messages: tuple[ChatMessage, ...]
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout: Optional[int] = None
    # Provider-facing tool definitions (empty => no tool calling).
    tools: tuple[ToolSpec, ...] = ()
    # Reserved for later: provider hints, metadata, request ids for usage tracking.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResponse:
    """A normalized provider response returned to the caller."""

    content: str
    provider: str
    model: str
    usage: Optional[UsageStats] = None
    raw: Optional[dict] = None
    # Populated when the provider asks the caller to run tools.
    tool_calls: tuple[ToolCall, ...] = ()
    finish_reason: str = "stop"


@dataclass
class ProviderConfig:
    """Configuration for a single LLM provider instance (built from env vars)."""

    name: str = "groq"
    api_key: str = ""
    base_url: str = GROQ_DEFAULT_BASE_URL
    model: str = GROQ_DEFAULT_MODEL
    timeout: int = 60
    max_tokens: int = 1024
    temperature: float = 0.7
    enabled: bool = True
    priority: int = 100
    rate_limit_per_minute: Optional[int] = None
