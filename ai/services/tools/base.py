"""Controlled tool abstractions for the AI service.

The LLM never touches the database, Django models, or application code
directly. It can only request registered tools by name, and each tool:

    - declares a JSON schema of allowed params,
    - receives only a server-built ToolContext (never raw user objects/json),
    - returns plain serializable dicts (or a controlled {"error": ...} dict),
    - enforces the same permission rules as the corresponding ContribKit views.

Only parameters declared in the tool's schema are forwarded; anything else the
LLM invents (e.g. ``user_id=...``) is dropped or returned as an error.
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from ..types import ToolSpec

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    """Server-controlled context passed to tools — never built by the LLM."""

    # Django request.user (authenticated or AnonymousUser).
    user: Any = None
    # Path the user is currently viewing (server-provided by the chat view).
    page_path: Optional[str] = None
    # Explicit issue id supplied by the page/view layer when available.
    issue_id: Optional[int] = None


class AITool:
    """Base class for a single controlled capability exposed to the LLM."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    def run(self, context: ToolContext, **kwargs) -> dict[str, Any]:
        raise NotImplementedError("Subclasses must implement run().")


class ToolRegistry:
    """Registers tools, advertises them to providers, executes them safely."""

    def __init__(self):
        self._tools: dict[str, AITool] = {}

    def register(self, tool: AITool) -> None:
        if not isinstance(tool, AITool):
            raise TypeError("ToolRegistry.register() expects an AITool instance.")
        if not tool.name:
            raise ValueError("Tools must have a name.")
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[AITool]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> tuple[ToolSpec, ...]:
        """Tool definitions sent to the provider (provider serializes them)."""
        return tuple(
            ToolSpec(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters,
            )
            for tool in self._tools.values()
        )

    def execute(self, name: str, arguments: Optional[dict], context: ToolContext) -> dict[str, Any]:
        """Execute a tool call with strict param filtering.

        Never raises: failures are returned as controlled error dicts so the
        LLM can answer gracefully, and no internals (stack traces, query
        details, creds) leak into the model or client.
        """
        tool = self._tools.get(name)
        if tool is None:
            return {"error": f"Unknown tool: '{name}'.", "tool": name}

        allowed = set(tool.parameters.get("properties", {}))
        clean_args = {
            key: value
            for key, value in (arguments or {}).items()
            if key in allowed
        }
        try:
            return tool.run(context=context, **clean_args)
        except Exception:  # noqa: BLE001 — boundary: any tool failure is contained
            logger.exception("AI tool '%s' failed", name)
            return {"error": "Tool execution failed. Please try again or rephrase."}
