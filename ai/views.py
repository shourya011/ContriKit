"""Views for the AI service layer.

- ``GET  /ai/health/`` — diagnostics (no API call, no secrets, monitoring-safe).
- ``POST /ai/chat/``  — the chatbot endpoint. Thin JSON view: validates input,
  enforces auth (same 403 ``login_required`` convention as
  ``issues.toggle_save_view``), rate limits per user, then calls the existing
  AI service (``ai_assistant_chat``) with server-side user/page context.

No UI logic lives here; the frontend is a static widget in
``templates/ai/widget.html`` driven by ``static/js/ai_chat.js``.
"""

import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .services import (
    AIServiceError,
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMProviderServerError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
    ai_assistant_chat,
    get_ai_service,
)
from .services.chat_session import append_message, get_history, is_rate_limited

logger = logging.getLogger(__name__)

MAX_SOURCES = 6

# Tool names that produce "source" links for the UI.
ISSUE_TOOLS = {"search_issues", "recommend_issues", "get_issue_details", "get_current_issue_context"}
TEMPLATE_TOOLS = {"search_templates", "recommend_templates", "get_template"}


@require_GET
def ai_health_view(request):
    """Report AI service status.

    Safe for unauthenticated monitoring: it never calls the LLM API and
    returns only provider names, booleans, and model names — no secrets.
    """
    return JsonResponse(get_health_payload())


@require_POST
def ai_chat_view(request):
    """JSON endpoint for one assistant turn.

    Body: ``{"message": "..."}`` (only the message travels from the client).
    Page/issue context is resolved server-side from ``request.path`` and
    ``request.user`` — the client never sends identity or page data.
    """
    if not request.user.is_authenticated:
        # Same convention as issues.toggle_save_view: 403 + login_required.
        return JsonResponse({"error": "login_required"}, status=403)

    data = _parse_json(request)
    if data is None:
        return JsonResponse(
            {"error": "Invalid JSON payload.", "code": "invalid_json"}, status=400
        )

    message = (data.get("message") or "").strip()
    if not message:
        return JsonResponse(
            {"error": "Message cannot be empty.", "code": "empty_message"}, status=400
        )

    max_length = int(getattr(settings, "AI_CHAT_MAX_MESSAGE_LENGTH", 2000))
    if len(message) > max_length:
        return JsonResponse(
            {"error": f"Message is too long (max {max_length} characters).", "code": "message_too_long"},
            status=400,
        )

    if is_rate_limited(request.session):
        return JsonResponse(
            {"error": "You are sending messages too quickly. Please wait a moment.", "code": "rate_limited"},
            status=429,
        )

    history = get_history(request.session)
    tool_events = []
    try:
        response = ai_assistant_chat(
            message,
            user=request.user,
            page_path=request.path,
            history=history,
            tool_events=tool_events,
        )
    except LLMConfigurationError as exc:
        # No provider credentials at all (e.g. AI_GROQ_API_KEY empty/unset).
        logger.warning("AI chat not configured: %s", exc)
        return JsonResponse(
            {
                "error": (
                    "The AI assistant is not configured yet. Set "
                    "AI_GROQ_API_KEY in your .env file (see .env.example) and "
                    "restart the server, then test with `python manage.py ai_test`."
                ),
                "code": "ai_not_configured",
                "hint": "AI_GROQ_API_KEY",
            },
            status=503,
        )
    except LLMAuthenticationError as exc:
        # A key IS set but the provider rejected it (HTTP 401/403).
        logger.error("AI provider auth failure: %s", exc)
        return JsonResponse(
            {
                "error": (
                    "The AI provider rejected the API key. Check that "
                    "AI_GROQ_API_KEY in your .env file is a valid Groq key "
                    "(it starts with gsk_)."
                ),
                "code": "provider_auth_failed",
            },
            status=503,
        )
    except LLMProviderServerError as exc:
        logger.error("AI provider server error: %s", exc)
        return JsonResponse(
            {
                "error": "The AI provider is having trouble right now. Please try again shortly.",
                "code": "provider_error",
            },
            status=503,
        )
    except LLMProviderUnavailableError as exc:
        logger.warning("AI provider unavailable: %s", exc)
        return JsonResponse(
            {
                "error": "The AI provider is unreachable right now. Please check your connection and try again shortly.",
                "code": "ai_unavailable",
            },
            status=503,
        )
    except LLMTimeoutError as exc:
        logger.warning("AI chat timed out: %s", exc)
        return JsonResponse(
            {
                "error": "The AI assistant is taking too long. Please try again.",
                "code": "ai_timeout",
            },
            status=504,
        )
    except LLMRateLimitError as exc:
        logger.warning("AI provider rate limited: %s", exc)
        return JsonResponse(
            {
                "error": "The AI provider is busy. Please try again shortly.",
                "code": "provider_rate_limited",
            },
            status=429,
        )
    except LLMInvalidResponseError as exc:
        logger.error("AI provider returned an invalid response: %s", exc)
        return JsonResponse(
            {
                "error": "The AI provider returned an unexpected response. Please try again.",
                "code": "provider_error",
            },
            status=503,
        )
    except LLMProviderError as exc:
        # Client 4xx such as HTTP 404 for a retired Groq model ID.
        logger.error(
            "AI provider request failed (HTTP %s): %s",
            getattr(exc, "status_code", None),
            exc,
        )
        return JsonResponse(
            {
                "error": (
                    "The AI provider rejected this request. Check that "
                    "AI_GROQ_MODEL is a current Groq model (see .env.example)."
                ),
                "code": "provider_error",
            },
            status=503,
        )
    except AIServiceError as exc:
        logger.exception("AI chat failed: %s", exc)
        return JsonResponse(
            {"error": "Something went wrong while answering. Please try again.", "code": "ai_error"},
            status=500,
        )

    append_message(request.session, "user", message)
    append_message(request.session, "assistant", response.content)

    return JsonResponse(
        {
            "reply": response.content,
            "sources": _build_sources(tool_events),
            "provider": response.provider,
            "model": response.model,
        }
    )


# ── Helpers (kept module-level for straightforward unit testing) ───────────

def get_health_payload() -> dict:
    return get_ai_service().health()


def _parse_json(request):
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _add_source(sources, seen, source_type, label, url):
    key = (source_type, url)
    if key in seen or not url:
        return
    seen.add(key)
    sources.append({"type": source_type, "label": label, "url": url})


def _issue_source(sources, seen, issue):
    if not isinstance(issue, dict):
        return
    _add_source(sources, seen, "issue", issue.get("title") or f"Issue #{issue.get('id')}", f"/issues/{issue.get('id')}/")


def _template_source(sources, seen, template):
    if not isinstance(template, dict):
        return
    _add_source(sources, seen, "template", template.get("title") or template.get("slug"), f"/templates/{template.get('slug')}/")


def _build_sources(tool_events, max_sources=MAX_SOURCES) -> list[dict]:
    """Turn executed tool results into small UI source links (deduped, capped).

    Only public, already-retrieved data is used; errors are skipped. This runs
    on tool results fetched through the controlled registry — never on raw LLM
    output, so the model cannot invent URLs.
    """
    sources, seen = [], set()
    for event in tool_events or []:
        name = event.get("name")
        result = event.get("result") or {}
        if not isinstance(result, dict) or "error" in result:
            continue

        if name in ISSUE_TOOLS:
            issues = []
            if name == "get_current_issue_context":
                if result.get("available"):
                    issues.append(result)
            elif name == "get_issue_details":
                issues.append(result.get("issue"))
            else:
                issues.extend(item.get("issue") for item in result.get("results", []))
            for issue in issues:
                _issue_source(sources, seen, issue)

        elif name in TEMPLATE_TOOLS:
            templates = []
            if name == "get_template":
                templates.append(result.get("template"))
            else:
                templates.extend(result.get("results", []))
            for template in templates:
                _template_source(sources, seen, template)

        elif name == "search_git_commands":
            if result.get("results"):
                _add_source(sources, seen, "cheatsheet", "Git Cheat Sheet", "/cheatsheet/")

        elif name == "get_github_repository":
            repo = result.get("repository")
            if isinstance(repo, dict):
                _add_source(sources, seen, "github", repo.get("full_name") or repo.get("html_url"), repo.get("html_url"))

        elif name == "get_github_beginner_issues":
            for item in result.get("results", []):
                if isinstance(item, dict):
                    _add_source(sources, seen, "github", item.get("title"), item.get("url"))

    return sources[:max_sources]
