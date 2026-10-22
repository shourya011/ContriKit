"""GitHub tools: thin wrappers over the project's shared GitHub client.

Reuses ``repos.github_api`` (the same code the editor repo linking and bulk
import views use) — no GitHub API logic is duplicated. The optional
``GITHUB_PAT`` is applied server-side and never returned to the model.
"""

from repos.github_api import fetch_github_issues_api, get_repository, parse_github_url

from .base import AITool, ToolContext

MAX_ISSUES = 5


def _resolve_target(url="", owner="", repo=""):
    if url:
        owner, repo = parse_github_url(url)
    elif owner and repo:
        owner, repo = owner.strip(), repo.strip()
    else:
        return None, None
    return owner, repo


class GetGitHubRepositoryTool(AITool):
    """Fetch public metadata for a GitHub repository via the shared API."""

    name = "get_github_repository"
    description = (
        "Fetch public metadata for a GitHub repository (stars, language, "
        "description, default branch info) using the project's GitHub API. "
        "Accepts either a full repository URL or owner + repo name."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full GitHub repository URL, e.g. https://github.com/django/django"},
            "owner": {"type": "string", "description": "Owner (if no URL)."},
            "repo": {"type": "string", "description": "Repository name (if no URL)."},
        },
    }

    def run(self, context: ToolContext, url="", owner="", repo="") -> dict:
        owner, repo = _resolve_target(url, owner, repo)
        if not owner or not repo:
            return {"error": "Provide a valid GitHub repository URL, or both owner and repo."}
        result = get_repository(owner, repo)
        if not result["ok"]:
            return {"error": result["error"], "status_code": result["status_code"]}
        data = result["data"]
        return {
            "repository": {
                "full_name": data.get("full_name"),
                "description": data.get("description"),
                "language": data.get("language"),
                "stars": data.get("stargazers_count"),
                "forks": data.get("forks_count"),
                "open_issues": data.get("open_issues_count"),
                "topics": data.get("topics") or [],
                "html_url": data.get("html_url"),
                "default_branch": data.get("default_branch"),
            }
        }


class GetGitHubBeginnerIssuesTool(AITool):
    """Fetch open beginner-labeled issues from GitHub for a repository."""

    name = "get_github_beginner_issues"
    description = (
        "Fetch open GitHub issues labeled 'good first issue'/'beginner'/'starter' "
        "for a repository, using the same bulk import logic as the editor tools. "
        "Use when the user asks about live GitHub issues beyond ContribKit's "
        "curated board."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full GitHub repository URL."},
            "owner": {"type": "string"},
            "repo": {"type": "string"},
            "limit": {"type": "integer", "description": f"Max issues (1-{MAX_ISSUES}, default {MAX_ISSUES})."},
        },
    }

    def run(self, context: ToolContext, url="", owner="", repo="", limit=MAX_ISSUES) -> dict:
        owner, repo = _resolve_target(url, owner, repo)
        if not owner or not repo:
            return {"error": "Provide a valid GitHub repository URL, or both owner and repo."}
        issues = fetch_github_issues_api(owner, repo)
        if not issues:
            return {"count": 0, "results": [], "note": "No open beginner-labeled issues found for this repository."}
        limit = max(1, min(int(limit or MAX_ISSUES), MAX_ISSUES))
        results = [
            {
                "title": issue["title"],
                "url": issue["url"],
                "labels": issue["labels"],
                "comments": issue["comments"],
                "created_at": issue["created_at"],
                # Body is a snippet only; full context lives on GitHub.
                "body_preview": (issue["body"] or "")[:800],
            }
            for issue in issues[:limit]
        ]
        return {"count": len(results), "results": results}
