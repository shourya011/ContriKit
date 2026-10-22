"""Template Library tools: the same data exposed on /templates/.

Uses the exact search semantics from ``templates_app/views.py``
(title/category/tags/description) and never exposes template authors or
internal fields beyond what the template detail page shows.
"""

import re

from django.db.models import Q
from templates_app.models import Template

from .base import AITool, ToolContext

MAX_RESULTS = 10
DEFAULT_RESULTS = 5
MAX_CONTENT_CHARS = 9000

SEARCH_CATEGORIES = [choice[0] for choice in Template.CATEGORY_CHOICES]


def _template_dict(template, include_content=True, max_content=MAX_CONTENT_CHARS):
    content = template.content
    truncated = False
    if include_content and len(content) > max_content:
        content = content[:max_content]
        truncated = True
    return {
        "slug": template.slug,
        "title": template.title,
        "category": template.category,
        "description": template.description,
        "tags": [tag.strip() for tag in template.tag_list],
        "content": content if include_content else None,
        "content_truncated": truncated,
        "updated_at": template.updated_at.isoformat(),
    }


def _tokens(text: str):
    return {
        token
        for token in re.findall(r"[a-z0-9+#.-]{2,}", (text or "").lower())
        if token not in {"a", "an", "and", "for", "the", "of", "to", "with", "i", "me", "my", "we", "need", "want", "like", "please", "help", "template", "file", "create"}
    }


class SearchTemplatesTool(AITool):
    """Search the ContribKit template library by keyword/category."""

    name = "search_templates"
    description = (
        "Search the ContribKit repository template library (README template, "
        "CONTRIBUTING.md, issue/PR templates, CODE_OF_CONDUCT, licenses, "
        "GitHub config files). Filters by keyword or category."
    )
    parameters = {
        "type": "object",
        "properties": {
            "q": {"type": "string", "description": "Keyword: title, description, tags, or content."},
            "category": {"type": "string", "description": f"One of: {', '.join(SEARCH_CATEGORIES)}"},
            "limit": {"type": "integer", "description": "Max results (1-10, default 5)."},
        },
    }

    def run(self, context: ToolContext, q="", category="", limit=DEFAULT_RESULTS) -> dict:
        templates = Template.objects.all()
        if category and category != "all":
            templates = templates.filter(category=category)
        if q:
            templates = templates.filter(
                Q(title__icontains=q)
                | Q(category__icontains=q)
                | Q(tags__icontains=q)
                | Q(description__icontains=q)
            )
        templates = templates.order_by("category", "title")
        limit = max(1, min(int(limit or DEFAULT_RESULTS), MAX_RESULTS))
        results = [_template_dict(template, include_content=False) for template in templates[:limit]]
        return {"count": len(results), "results": results}


class GetTemplateTool(AITool):
    """Retrieve the full contents of one template (content capped)."""

    name = "get_template"
    description = (
        "Retrieve the full content of a specific ContribKit repository template "
        "by slug (e.g. 'contributing-md', 'pr-template'). Use after "
        "search_templates. Content is truncated at 9000 characters."
    )
    parameters = {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "description": "Template slug from search results."},
        },
        "required": ["slug"],
    }

    def run(self, context: ToolContext, slug="") -> dict:
        if not slug:
            return {"error": "slug is required."}
        try:
            template = Template.objects.get(slug=slug)
        except Template.DoesNotExist:
            return {"error": f"No template with slug '{slug}' was found."}
        return {"template": _template_dict(template, include_content=True)}


class RecommendTemplatesTool(AITool):
    """Recommend templates relevant to a contribution task (deterministic)."""

    name = "recommend_templates"
    description = (
        "Recommend the most relevant ContribKit repository templates for a "
        "contribution activity, e.g. 'I need a PR template for a Python repo' "
        "or 'getting-started docs for contributors'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "preference": {"type": "string", "description": "The contribution context, e.g. 'PR template for Python changes'."},
            "category": {"type": "string", "description": f"Optional category: {', '.join(SEARCH_CATEGORIES)}"},
            "limit": {"type": "integer", "description": "Max results (1-10, default 3)."},
        },
        "required": ["preference"],
    }

    def run(self, context: ToolContext, preference="", category="", limit=3) -> dict:
        terms = _tokens(preference)
        templates = Template.objects.all()
        if category and category != "all":
            templates = templates.filter(category=category)

        scored = []
        for template in templates:
            title = template.title.lower()
            tags = {tag.lower() for tag in template.tag_list}
            haystack = f"{title} {template.category} {template.description}".lower()
            score = 0
            matched = []
            for term in terms:
                if term in title:
                    score += 3
                    matched.append(term)
                if term in tags:
                    score += 3
                    matched.append(term)
                if term in haystack:
                    score += 1
                    if term not in matched:
                        matched.append(term)
            if score:
                scored.append((score, template, matched))

        scored.sort(key=lambda item: item[0], reverse=True)
        limit = max(1, min(int(limit or 3), MAX_RESULTS))
        results = [
            {**_template_dict(template, include_content=False), "matched_terms": matched}
            for score, template, matched in scored[:limit]
        ]
        return {"count": len(results), "results": results}
