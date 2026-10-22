"""AI service layer public API.

Usage from anywhere in the project:

    from ai.services import ai_assistant_chat, ai_chat, ChatMessage

    # Plain LLM call:
    response = ai_chat([ChatMessage(role="user", content="Help me...")])

    # ContribKit-aware assistant call (system prompt + controlled tools):
    response = ai_assistant_chat(
        "Suggest beginner Python issues",
        user=request.user,
        page_path=request.path,
    )

Tool registry (controlled capabilities, no direct DB/LLM access):
    from ai.services.tools import build_default_tool_registry
"""

from .exceptions import (
    AIServiceError,
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMProviderServerError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from .prompts import build_system_prompt
from .router import LLMRouter
from .service import (
    AIService,
    ai_assistant_chat,
    ai_chat,
    get_ai_service,
)
from .tools import ToolContext, ToolRegistry, build_default_tool_registry
from .types import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ProviderConfig,
    ToolCall,
    ToolSpec,
    UsageStats,
)

__all__ = [
    "AIService",
    "LLMRouter",
    "ai_chat",
    "ai_assistant_chat",
    "get_ai_service",
    "build_system_prompt",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ProviderConfig",
    "ToolCall",
    "ToolSpec",
    "UsageStats",
    "ToolContext",
    "ToolRegistry",
    "build_default_tool_registry",
    "AIServiceError",
    "LLMConfigurationError",
    "LLMProviderError",
    "LLMProviderServerError",
    "LLMTimeoutError",
    "LLMAuthenticationError",
    "LLMRateLimitError",
    "LLMProviderUnavailableError",
    "LLMInvalidResponseError",
]
