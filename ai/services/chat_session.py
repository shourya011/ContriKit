"""Per-user chat session state: rate limiting and short conversation history.

Stored in the existing Django session (the same mechanism the project already
uses for issue view tracking) — no database models, no new tables. This keeps
conversation history server-side so the client can never inject fake system
messages, and gives simple per-user rate limiting that survives process
restarts on PythonAnywhere.
"""

import time

from django.conf import settings

from .types import ChatMessage

HISTORY_KEY = "ai_chat_history"
RATE_KEY = "ai_chat_rate"

MAX_STORED_MESSAGE_CHARS = 4000


def _history_limit() -> int:
    return int(getattr(settings, "AI_CHAT_HISTORY_LIMIT", 12))


def get_history(session) -> list[ChatMessage]:
    """Return validated history (user/assistant only) for the assistant call."""
    raw = session.get(HISTORY_KEY, []) or []
    history = []
    for item in raw[-_history_limit():]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            history.append(ChatMessage(role=role, content=content[:MAX_STORED_MESSAGE_CHARS]))
    return history


def append_message(session, role: str, content: str) -> None:
    """Append one user/assistant turn to session history (capped)."""
    if role not in ("user", "assistant"):
        raise ValueError("Only user/assistant turns are stored.")
    entries = session.get(HISTORY_KEY, []) or []
    entries.append({"role": role, "content": content[:MAX_STORED_MESSAGE_CHARS]})
    session[HISTORY_KEY] = entries[-_history_limit():]


def is_rate_limited(session) -> bool:
    """Sliding-window per-session rate limit (limits attempts, not just calls).

    Returns True when the user exceeded AI_CHAT_RATE_LIMIT requests within
    AI_CHAT_RATE_WINDOW seconds.
    """
    limit = int(getattr(settings, "AI_CHAT_RATE_LIMIT", 10))
    window = int(getattr(settings, "AI_CHAT_RATE_WINDOW", 60))
    now = time.time()

    stamps = [t for t in (session.get(RATE_KEY, []) or []) if now - t < window]
    if limit > 0 and len(stamps) >= limit:
        session[RATE_KEY] = stamps
        return True

    stamps.append(now)
    # Keep only a bounded tail to avoid unbounded session growth.
    session[RATE_KEY] = stamps[-(limit * 4 if limit else 40):]
    return False
