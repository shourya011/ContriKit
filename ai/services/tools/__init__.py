"""ContribKit-aware tools registry.

`build_default_tool_registry()` returns every controlled capability the AI can
use. Registering a new tool is one class + one line here — nothing else in the
service layer changes.
"""

from .base import AITool, ToolContext, ToolRegistry
from .cheatsheet import SearchGitCommandsTool
from .github import GetGitHubBeginnerIssuesTool, GetGitHubRepositoryTool
from .issues import GetIssueDetailsTool, RecommendIssuesTool, SearchIssuesTool
from .page import GetCurrentIssueContextTool, GetCurrentTemplateContextTool
from .templates import GetTemplateTool, RecommendTemplatesTool, SearchTemplatesTool
from .user import GetUserContextTool

__all__ = [
    "AITool",
    "ToolContext",
    "ToolRegistry",
    "build_default_tool_registry",
    "SearchIssuesTool",
    "GetIssueDetailsTool",
    "RecommendIssuesTool",
    "SearchTemplatesTool",
    "GetTemplateTool",
    "RecommendTemplatesTool",
    "SearchGitCommandsTool",
    "GetGitHubRepositoryTool",
    "GetGitHubBeginnerIssuesTool",
    "GetUserContextTool",
    "GetCurrentIssueContextTool",
    "GetCurrentTemplateContextTool",
]

DEFAULT_TOOLS = (
    SearchIssuesTool,
    GetIssueDetailsTool,
    RecommendIssuesTool,
    SearchTemplatesTool,
    GetTemplateTool,
    RecommendTemplatesTool,
    SearchGitCommandsTool,
    GetGitHubRepositoryTool,
    GetGitHubBeginnerIssuesTool,
    GetUserContextTool,
    GetCurrentIssueContextTool,
    GetCurrentTemplateContextTool,
)


def build_default_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool_cls in DEFAULT_TOOLS:
        registry.register(tool_cls())
    return registry
