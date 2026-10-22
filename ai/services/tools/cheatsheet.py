"""Git Cheat Sheet tools: the same commands exposed on /cheatsheet/.

Reads CheatSheetSection/CheatSheetCommand only — the AI can explain or
assemble workflows from real commands but never fabricates tooling.
"""

from django.db.models import Q
from cheatsheet.models import CheatSheetCommand

from .base import AITool, ToolContext

MAX_RESULTS = 10
DEFAULT_RESULTS = 8


class SearchGitCommandsTool(AITool):
    """Search the ContribKit Git cheat sheet by keyword or section."""

    name = "search_git_commands"
    description = (
        "Search ContribKit's Git cheat sheet for real git/GitHub commands. "
        "Use when the user asks how to clone, branch, stage, commit, push, "
        "sync a fork, open a PR, or undo git mistakes. Filters by section "
        "(e.g. setup, branching, staging) or keyword."
    )
    parameters = {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "Keyword: command, description, or example."},
            "section": {"type": "string", "description": "Cheat sheet section title, e.g. 'Branching', 'Undoing Mistakes'."},
            "limit": {"type": "integer", "description": "Max results (1-10, default 8)."},
        },
    }

    def run(self, context: ToolContext, q="", section="", limit=DEFAULT_RESULTS) -> dict:
        commands = CheatSheetCommand.objects.select_related("section")
        if q:
            commands = commands.filter(
                Q(command__icontains=q)
                | Q(description__icontains=q)
                | Q(example__icontains=q)
                | Q(section__title__icontains=q)
            )
        if section:
            commands = commands.filter(section__title__iexact=section)
        commands = commands.order_by("section__order", "order", "command")

        limit = max(1, min(int(limit or DEFAULT_RESULTS), MAX_RESULTS))
        results = [
            {
                "command": cmd.command,
                "description": cmd.description,
                "example": cmd.example,
                "section": cmd.section.title,
            }
            for cmd in commands[:limit]
        ]
        return {"count": len(results), "results": results}
