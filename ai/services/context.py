"""Server-built request context for the AI assistant.

The future chat view will pass ``request.user`` and ``request.path`` here;
context is resolved server-side (never from LLM input) so the model receives
only what ContribKit considers public or user-owned.

Frontend context integration is NOT implemented yet — this module provides the
backend plumbing it will use.
"""

import re

from issues.models import Issue
from templates_app.models import Template

ISSUE_PATH_RE = re.compile(r"^/issues/(?P<issue_id>\d+)/")
TEMPLATE_PATH_RE = re.compile(r"^/templates/(?P<slug>[a-z0-9-]+)/")


def build_user_context(user) -> dict:
    """Safe subset of the authenticated user's own profile (no email)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return {"authenticated": False}
    return {
        "authenticated": True,
        "username": getattr(user, "username", ""),
        "role": getattr(user, "role", "viewer"),
        "github_username": getattr(user, "github_username", "") or "",
        "bio": (getattr(user, "bio", "") or "")[:500],
        "is_editor": bool(getattr(user, "is_editor", False)),
        "is_platform_admin": bool(getattr(user, "is_platform_admin", False)),
    }


def build_page_context(page_path: str | None) -> dict:
    """Resolve what the user is currently viewing (issue/template pages only).

    Returns {"page": "unknown", ...} for everything else so the model never
    guesses about pages it has no data for.
    """
    if not page_path:
        return {"page": "unknown", "available": False}

    issue_match = ISSUE_PATH_RE.match(page_path)
    if issue_match:
        try:
            issue = (
                Issue.objects.select_related("repo")
                .prefetch_related("tags")
                .get(id=int(issue_match.group("issue_id")))
            )
        except Issue.DoesNotExist:
            return {"page": "issue", "available": False}
        return {
            "page": "issue",
            "available": True,
            "issue": {
                "id": issue.id,
                "title": issue.title,
                "difficulty": issue.difficulty,
                "estimated_hours": float(issue.estimated_hours),
                "repo": issue.repo.name,
                "tags": [tag.name for tag in issue.tags.all()],
            },
        }

    template_match = TEMPLATE_PATH_RE.match(page_path)
    if template_match:
        try:
            template = Template.objects.get(slug=template_match.group("slug"))
        except Template.DoesNotExist:
            return {"page": "template", "available": False}
        return {
            "page": "template",
            "available": True,
            "template": {
                "slug": template.slug,
                "title": template.title,
                "category": template.category,
            },
        }

    return {"page": "unknown", "available": False, "path": page_path[:200]}
