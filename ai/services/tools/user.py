"""User Context tool: safe, permission-scoped info about the authenticated user.

Privacy rules enforced here (mirror ContribKit's own rule set):
    - Only the *current* user's profile is ever returned (from ToolContext).
    - The LLM cannot request another user by id/name — there is no such param.
    - Email is never exposed; only username, role, github_username, bio.
    - Saved issues / posted issues are the user's own (or public counts).
"""

from issues.models import Issue

from .base import AITool, ToolContext

MAX_SAVED = 5


class GetUserContextTool(AITool):
    """Return safe details about the currently authenticated user."""

    name = "get_user_context"
    description = (
        "Get safe context about the currently signed-in ContribKit user: "
        "username, role (viewer/editor/admin), GitHub username, bio, and their "
        "own saved/posted issues. Returns authenticated=false for guests. "
        "Never reveals other users' private data."
    )
    parameters = {
        "type": "object",
        "properties": {},
    }

    def run(self, context: ToolContext) -> dict:
        user = context.user
        if user is None or not getattr(user, "is_authenticated", False):
            return {"authenticated": False}

        saved = (
            user.savedissue_set.select_related("issue", "issue__repo")
            .order_by("-saved_at")[:MAX_SAVED]
            if hasattr(user, "savedissue_set")
            else []
        )
        data = {
            "authenticated": True,
            "username": user.username,
            "role": user.role,
            "is_viewer": user.is_viewer,
            "is_editor": user.is_editor,
            "is_platform_admin": user.is_platform_admin,
            "github_username": user.github_username or "",
            "bio": user.bio or "",
            "saved_issues_count": user.savedissue_set.count(),
            "saved_issues": [
                {
                    "id": bookmark.issue_id,
                    "title": bookmark.issue.title,
                    "url": f"/issues/{bookmark.issue_id}/",
                    "repo": bookmark.issue.repo.name,
                }
                for bookmark in saved
            ],
        }
        if user.is_editor:
            data["posted_issues_count"] = Issue.objects.filter(posted_by=user).count()
            data["linked_repos_count"] = user.repos.count()
            data["repositories"] = list(
                user.repos.values("name", "language", "stars")[:MAX_SAVED]
            )
        return data
