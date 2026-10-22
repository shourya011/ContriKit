"""Page / Issue Context tools.

Backend plumbing for page awareness: the future chat view supplies
``page_path`` (and/or ``issue_id``) in ToolContext; the tool resolves the
*current* ContribKit issue/template page server-side. The frontend context
integration (sending the path) is intentionally separate and comes later.
"""

import re

from issues.models import Issue
from templates_app.models import Template

from .base import AITool, ToolContext

ISSUE_PATH_RE = re.compile(r"^/issues/(?P<issue_id>\d+)/")
TEMPLATE_PATH_RE = re.compile(r"^/templates/(?P<slug>[a-z0-9-]+)/")


class GetCurrentIssueContextTool(AITool):
    """Resolve the issue the user is currently viewing (server-side)."""

    name = "get_current_issue_context"
    description = (
        "Get the ContribKit issue the user is currently viewing. Use when the "
        "user references 'this issue' or asks about the page they are on. No "
        "arguments needed — the page is resolved from the server-side context. "
        "Returns available=false when no issue page is active."
    )
    parameters = {
        "type": "object",
        "properties": {},
    }

    def run(self, context: ToolContext) -> dict:
        issue_id = getattr(context, "issue_id", None)
        page_path = getattr(context, "page_path", "")

        if not issue_id and page_path:
            match = ISSUE_PATH_RE.match(page_path or "")
            if match:
                issue_id = int(match.group("issue_id"))

        if not issue_id:
            return {"available": False, "page_path": page_path}

        try:
            issue = (
                Issue.objects.select_related("repo", "posted_by")
                .prefetch_related("tags")
                .get(id=issue_id)
            )
        except Issue.DoesNotExist:
            return {"available": False, "error": "Current page references an issue that no longer exists."}

        return {
            "available": True,
            "issue_id": issue.id,
            "title": issue.title,
            "difficulty": issue.difficulty,
            "estimated_hours": float(issue.estimated_hours),
            "status": issue.status,
            "description": issue.description,
            "github_issue_url": issue.github_issue_url,
            "tags": [tag.name for tag in issue.tags.all()],
            "repo": {
                "name": issue.repo.name,
                "language": issue.repo.language,
                "stars": issue.repo.stars,
                "github_url": issue.repo.github_url,
            },
        }


class GetCurrentTemplateContextTool(AITool):
    """Resolve the template the user is currently viewing (server-side)."""

    name = "get_current_template_context"
    description = (
        "Get the ContribKit template the user is currently viewing, resolved "
        "from the server-side page context. Returns available=false when the "
        "user is not on a template page."
    )
    parameters = {
        "type": "object",
        "properties": {},
    }

    def run(self, context: ToolContext) -> dict:
        page_path = getattr(context, "page_path", "")
        match = TEMPLATE_PATH_RE.match(page_path or "")
        if not match:
            return {"available": False, "page_path": page_path}
        slug = match.group("slug")
        try:
            template = Template.objects.get(slug=slug)
        except Template.DoesNotExist:
            return {"available": False, "error": f"No template with slug '{slug}'."}
        return {
            "available": True,
            "slug": template.slug,
            "title": template.title,
            "category": template.category,
            "description": template.description,
            "tags": template.tag_list,
        }
