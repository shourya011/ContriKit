"""Issue Board tools: the same data the public issue board exposes.

Mirrors the filters implemented in ``issues/views.py`` (keyword, language,
difficulty, tag) so recommendations match what a user would see on
``/issues/`` — no extra data, no admin/editor internals.
"""

import re

from django.db.models import Q
from issues.models import Issue

from .base import AITool, ToolContext

# Words that carry no signal for matching a contribution request.
STOPWORDS = {
    "a", "an", "and", "are", "be", "beginner", "can", "code", "contribute",
    "contributing", "do", "find", "for", "from", "get", "give", "good",
    "help", "i", "in", "into", "is", "issue", "issues", "like", "looking",
    "me", "my", "need", "of", "on", "or", "please", "project", "recommend",
    "some", "start", "suggest", "that", "the", "this", "to", "want", "was",
    "what", "with", "work", "would", "you",
}

MAX_RESULTS = 10
DEFAULT_RESULTS = 5


def _issue_dict(issue) -> dict:
    """Serializable, public-only representation of an Issue."""
    return {
        "id": issue.id,
        "title": issue.title,
        "difficulty": issue.difficulty,
        "estimated_hours": float(issue.estimated_hours),
        "status": issue.status,
        "is_featured": issue.is_featured,
        "view_count": issue.view_count,
        "github_issue_url": issue.github_issue_url,
        "created_at": issue.created_at.isoformat(),
        "tags": [
            {"name": tag.name, "slug": tag.slug, "color": tag.color}
            for tag in issue.tags.all()
        ],
        "repo": {
            "name": issue.repo.name,
            "language": issue.repo.language,
            "stars": issue.repo.stars,
            "github_url": issue.repo.github_url,
            "description": issue.repo.description,
        },
    }


def _base_queryset():
    return (
        Issue.objects.filter(status="open")
        .select_related("repo")
        .prefetch_related("tags")
        .order_by("-created_at")
    )


def _tokens(text: str):
    return {
        token
        for token in re.findall(r"[a-z0-9+#.-]{2,}", (text or "").lower())
        if token not in STOPWORDS
    }


def _limit(value, default=DEFAULT_RESULTS):
    try:
        return max(1, min(int(value), MAX_RESULTS))
    except (TypeError, ValueError):
        return default


class SearchIssuesTool(AITool):
    """Search the ContribKit issue board. Mirrors the public /issues filters."""

    name = "search_issues"
    description = (
        "Search beginner contribution opportunities on the ContribKit issue board. "
        "Use when the user asks for issues/opportunities by keyword, programming "
        "language, difficulty (beginner/intermediate), or tech-stack tag. Returns "
        "matching open issues with links. Does not include closed issues."
    )
    parameters = {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "Keyword: title, description, or repo name."},
            "language": {"type": "string", "description": "Programming language, e.g. Python, JavaScript."},
            "difficulty": {"type": "string", "enum": ["beginner", "intermediate"]},
            "tag": {"type": "string", "description": "Tech stack tag slug, e.g. python, react, django."},
            "limit": {"type": "integer", "description": "Max results (1-10, default 5)."},
        },
    }

    def run(self, context: ToolContext, q="", language="", difficulty="", tag="", limit=DEFAULT_RESULTS) -> dict:
        issues = _base_queryset()
        if q:
            issues = issues.filter(
                Q(title__icontains=q)
                | Q(description__icontains=q)
                | Q(repo__name__icontains=q)
            )
        if language:
            issues = issues.filter(repo__language__iexact=language)
        if difficulty:
            issues = issues.filter(difficulty=difficulty)
        if tag:
            issues = issues.filter(tags__slug=tag)

        limit = _limit(limit)
        results = [{"issue": _issue_dict(issue)} for issue in issues[:limit]]
        return {"count": len(results), "results": results}


class GetIssueDetailsTool(AITool):
    """Retrieve the complete public details of one ContribKit issue."""

    name = "get_issue_details"
    description = (
        "Get the full public details (description, requirements, repo, tags, "
        "difficulty, estimated hours, GitHub link) of one ContribKit issue by "
        "its numeric id. Use after search_issues or when the user references a "
        "specific issue id."
    )
    parameters = {
        "type": "object",
        "properties": {
            "issue_id": {"type": "integer", "description": "ContribKit issue id (from search results)."},
        },
        "required": ["issue_id"],
    }

    def run(self, context: ToolContext, issue_id=None) -> dict:
        try:
            issue_id = int(issue_id)
        except (TypeError, ValueError):
            return {"error": "issue_id must be an integer."}
        try:
            issue = (
                Issue.objects.select_related("repo", "posted_by")
                .prefetch_related("tags")
                .get(id=issue_id)
            )
        except Issue.DoesNotExist:
            return {"error": f"No issue with id {issue_id} was found."}

        data = _issue_dict(issue)
        data["description"] = issue.description
        data["posted_by"] = issue.posted_by.username
        return {"issue": data}


class RecommendIssuesTool(AITool):
    """Deterministic issue recommendation based on a user's request.

    Scoring is keyword/tag overlap against the open issue board — the model
    never invents results, and results always come from the database.
    """

    name = "recommend_issues"
    description = (
        "Recommend suitable ContribKit issues for a user's natural-language "
        "request, optionally filtered by language/difficulty/tag. Returns the "
        "best-scoring open issues with the terms they matched."
    )
    parameters = {
        "type": "object",
        "properties": {
            "preference": {"type": "string", "description": "The user's request, e.g. 'Python beginner task with docs'."},
            "language": {"type": "string"},
            "difficulty": {"type": "string", "enum": ["beginner", "intermediate"]},
            "tag": {"type": "string"},
            "limit": {"type": "integer", "description": "Max results (1-10, default 5)."},
        },
        "required": ["preference"],
    }

    def run(self, context: ToolContext, preference="", language="", difficulty="", tag="", limit=DEFAULT_RESULTS) -> dict:
        terms = _tokens(preference)
        if language:
            terms.add(language.lower())
        if tag:
            terms.add(tag.lower())

        issues = _base_queryset()
        if language:
            issues = issues.filter(repo__language__iexact=language)
        if difficulty:
            issues = issues.filter(difficulty=difficulty)
        if tag:
            issues = issues.filter(tags__slug=tag)

        scored = []
        for issue in issues[:200]:  # cap the scoring window; never whole DB
            title = (issue.title or "").lower()
            description = (issue.description or "").lower()
            repo_name = (issue.repo.name or "").lower()
            repo_lang = (issue.repo.language or "").lower()
            tag_names = {t.name.lower() for t in issue.tags.all()}
            tag_slugs = {t.slug for t in issue.tags.all()}

            score = 0
            matched = []
            for term in terms:
                if term in title:
                    score += 3
                    matched.append(term)
                if term in tag_names or term in tag_slugs:
                    score += 3
                    matched.append(term)
                if term == repo_lang:
                    score += 2
                    matched.append(term)
                if term in repo_name:
                    score += 2
                    matched.append(term)
                if term in description:
                    score += 1
                    if term not in matched:
                        matched.append(term)
            if score:
                scored.append((score, issue, matched))

        if not terms and not scored:
            # No signal at all: return fresh open issues so the model has
            # something real to offer instead of inventing.
            scored = [(1, issue, []) for issue in issues[:DEFAULT_RESULTS]]

        scored.sort(key=lambda item: (item[0], item[1].view_count), reverse=True)
        limit = _limit(limit)
        results = [
            {"issue": _issue_dict(issue), "matched_terms": matched}
            for score, issue, matched in scored[:limit]
        ]
        return {"count": len(results), "results": results}
