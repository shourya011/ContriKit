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
from urllib.parse import urlsplit

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
TEMPLATE_TOOLS = {
    "search_templates",
    "recommend_templates",
    "get_template",
    "get_current_template_context",
}

# The chat POST always lands on /ai/chat/, so request.path is NOT the page the
# user is looking at. The widget sends its own path, which is validated here.
MAX_PAGE_PATH_LENGTH = 300

NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


@require_GET
def ai_health_view(request):
    """Report AI service status.

    Safe for unauthenticated monitoring: it never calls the LLM API and
    returns only provider names, booleans, and model names — no secrets.
    """
    return _json_response(get_health_payload())


@require_POST
def ai_chat_view(request):
    """JSON endpoint for one assistant turn.

    Body: ``{"message": "...", "page": "/issues/12/"}``. ``page`` is the
    browser's current path (optional, validated to be same-origin); identity
    is always taken from ``request.user``, never from the client.
    """
    if not request.user.is_authenticated:
        # Same convention as issues.toggle_save_view: 403 + login_required.
        return _json_error("login_required", "login_required", 403)

    data = _parse_json(request)
    if data is None:
        return _json_error("Invalid JSON payload.", "invalid_json", 400)

    raw_message = data.get("message")
    if not isinstance(raw_message, str):
        return _json_error("Message must be a string.", "invalid_message", 400)
    message = raw_message.strip()
    if not message:
        return _json_error("Message cannot be empty.", "empty_message", 400)

    max_length = int(getattr(settings, "AI_CHAT_MAX_MESSAGE_LENGTH", 2000))
    if len(message) > max_length:
        return _json_error(
            f"Message is too long (max {max_length} characters).",
            "message_too_long",
            400,
        )

    if is_rate_limited(request.session):
        return _json_error(
            "You are sending messages too quickly. Please wait a moment.",
            "rate_limited",
            429,
        )

    page_path = (
        _safe_page_path(data.get("page"))
        or _referer_path(request)
        or "/"
    )
    history = get_history(request.session)
    tool_events = []
    try:
        response = ai_assistant_chat(
            message,
            user=request.user,
            page_path=page_path,
            history=history,
            tool_events=tool_events,
        )
    except LLMConfigurationError as exc:
        # No provider credentials at all (e.g. AI_GROQ_API_KEY empty/unset).
        logger.warning("AI chat not configured: %s", exc)
        return _json_error(
            "The AI assistant is not configured yet. Set AI_GROQ_API_KEY in "
            "your .env file (see .env.example) and restart the server, then "
            "test with `python manage.py ai_test`.",
            "ai_not_configured",
            503,
            hint="AI_GROQ_API_KEY",
        )
    except LLMAuthenticationError as exc:
        # A key IS set but the provider rejected it (HTTP 401/403).
        logger.error("AI provider auth failure: %s", exc)
        return _json_error(
            "The AI provider rejected the API key. Check that "
            "AI_GROQ_API_KEY in your .env file is a valid Groq key "
            "(it starts with gsk_).",
            "provider_auth_failed",
            503,
        )
    except LLMTimeoutError as exc:
        logger.warning("AI chat timed out: %s", exc)
        return _json_error(
            "The AI assistant is taking too long. Please try again.",
            "ai_timeout",
            504,
        )
    except LLMRateLimitError as exc:
        logger.warning("AI provider rate limited: %s", exc)
        return _json_error(
            "The AI provider is busy. Please try again shortly.",
            "provider_rate_limited",
            429,
        )
    except LLMProviderServerError as exc:
        logger.error("AI provider server error: %s", exc)
        return _json_error(
            "The AI provider is having trouble right now. Please try again shortly.",
            "provider_error",
            503,
        )
    except LLMProviderUnavailableError as exc:
        logger.warning("AI provider unavailable: %s", exc)
        return _json_error(
            "The AI provider is unreachable right now. Please check your "
            "connection and try again shortly.",
            "ai_unavailable",
            503,
        )
    except LLMInvalidResponseError as exc:
        logger.error("AI provider returned an invalid response: %s", exc)
        return _json_error(
            "The AI provider returned an unexpected response. Please try again.",
            "provider_error",
            503,
        )
    except LLMProviderError as exc:
        # Client 4xx such as HTTP 404 for a retired Groq model ID.
        logger.error(
            "AI provider request failed (HTTP %s, code=%s): %s",
            getattr(exc, "status_code", None),
            getattr(exc, "code", None),
            exc,
        )
        return _json_error(
            "The AI provider rejected this request. Check that "
            "AI_GROQ_MODEL is a current Groq model (see .env.example).",
            "provider_error",
            503,
        )
    except AIServiceError as exc:
        logger.exception("AI chat failed: %s", exc)
        return _json_error(
            "Something went wrong while answering. Please try again.",
            "ai_error",
            500,
        )

    append_message(request.session, "user", message)
    append_message(request.session, "assistant", response.content)

    return _json_response(
        {
            "reply": response.content,
            "sources": _build_sources(tool_events),
            "provider": response.provider,
            "model": response.model,
        }
    )


# ── Helpers (kept module-level for straightforward unit testing) ───────────

def _json_response(payload: dict, status: int = 200) -> JsonResponse:
    response = JsonResponse(payload, status=status)
    for header, value in NO_STORE_HEADERS.items():
        response[header] = value
    return response


def _json_error(message: str, code: str, status: int, **extra) -> JsonResponse:
    return _json_response({"error": message, "code": code, **extra}, status=status)


def _safe_page_path(value) -> str | None:
    """Accept only a same-origin absolute path like ``/issues/12/``.

    The client supplies the page it is viewing; anything else (absolute URL,
    ``//host``, control characters) is ignored so it can never influence
    which server-side context or links are produced.
    """
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > MAX_PAGE_PATH_LENGTH:
        return None
    if not value.startswith("/") or value.startswith("//"):
        return None
    if any(char in value for char in "\r\n\t\\"):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None
    return parts.path or "/"


def _referer_path(request) -> str | None:
    """Best-effort page path for older clients that do not send ``page``."""
    parts = urlsplit(request.headers.get("Referer", ""))
    if parts.scheme not in ("http", "https") or parts.netloc != request.get_host():
        return None
    return _safe_page_path(parts.path)


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
    if not isinstance(issue, dict) or not issue.get("id"):
        return
    _add_source(
        sources,
        seen,
        "issue",
        issue.get("title") or f"Issue #{issue.get('id')}",
        f"/issues/{issue.get('id')}/",
    )


def _template_source(sources, seen, template):
    if not isinstance(template, dict) or not template.get("slug"):
        return
    _add_source(
        sources,
        seen,
        "template",
        template.get("title") or template.get("slug"),
        f"/templates/{template.get('slug')}/",
    )


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
            elif name == "get_current_template_context":
                if result.get("available"):
                    templates.append(result)
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
