"""Django system checks for the AI service configuration.

Why this exists: when Groq has no credentials the router short-circuits
*before* any HTTP call, so ``POST /ai/chat/`` answers
``503 {"code": "ai_unavailable"}`` and nothing is ever sent to Groq.
From the outside that is indistinguishable from a dead feature ("the
widget does nothing, there is no request to any API"), so the reason is
reported at startup by ``runserver`` / ``manage.py check`` instead of
only at request time.

Checks also explain the two classic "key is in .env but not configured"
causes:

- ``ai.W003`` — a leftover OS environment variable overrides ``.env``.
- ``ai.W004`` — the ``.env`` file itself is missing, duplicated, or has an
  encoding problem (UTF-8 BOM / UTF-16).
"""

from django.conf import settings
from django.core.checks import Warning, register


def _key_setting(name: str) -> str:
    from ai.services.service import PROVIDER_KEY_SETTINGS

    return PROVIDER_KEY_SETTINGS.get(name, "")


def _credential_hint(keys: list[str]) -> str:
    return (
        "Set at least one of these in .env (see .env.example): "
        + ", ".join(keys)
        + ". Then verify with `python manage.py ai_test`."
    )


@register()
def ai_provider_credentials(app_configs, **kwargs):
    """Warn when Groq has no API key, and explain why (if diagnosable)."""
    from ai.env_diagnostics import (
        config_issues,
        duplicate_keys,
        env_config_conflicts,
        find_env_file,
    )
    from ai.services.service import _provider_names

    names = _provider_names()
    known = [name for name in names if _key_setting(name)]
    configured = [name for name in known if getattr(settings, _key_setting(name), "")]
    if configured:
        # Even when a key is loaded, an override from the OS environment can
        # still surprise the user — surface it, but lighter than a W001.
        conflicts = env_config_conflicts()
        if conflicts:
            details = "; ".join(item["message"] for item in conflicts)
            return [
                Warning(
                    "The AI credentials were loaded from the OS environment "
                    "instead of .env. This can make the assistant use a stale "
                    "or empty key.",
                    hint=details + " Open a fresh terminal / restart the "
                    "server so the OS environment variable is not set, or "
                    "unset it with `Remove-Item Env:AI_GROQ_API_KEY` "
                    "(PowerShell) / `unset AI_GROQ_API_KEY` (bash).",
                    id="ai.W002",
                )
            ]
        return []

    key_names = sorted({_key_setting(name) for name in known if _key_setting(name)}) or [
        "AI_GROQ_API_KEY",
    ]
    warnings = [
        Warning(
            "The AI assistant has no Groq credentials, so /ai/chat/ will "
            "answer 503 'not configured' without calling Groq.",
            hint=_credential_hint(key_names) + " Diagnose with `python manage.py ai_env`.",
            id="ai.W001",
        )
    ]

    # The most common real-world cause of "key is in .env but still not
    # configured": an (often empty) environment variable shadows the file.
    for conflict in env_config_conflicts():
        warnings.append(
            Warning(
                f"Environment variable {conflict['key']} overrides .env. "
                "python-decouple checks os.environ FIRST, so the .env value "
                "is never used for this key.",
                hint=(
                    "In the terminal that starts Django, the variable is "
                    f"{'EMPTY' if conflict['env_var_empty'] else 'set to a different value'}. "
                    "Open a NEW terminal (old PowerShell/cmd sessions keep "
                    "stale variables; check with `$env:AI_GROQ_API_KEY`), or "
                    "clear it before starting the server: "
                    "`Remove-Item Env:AI_GROQ_API_KEY` (PowerShell) / "
                    "`unset AI_GROQ_API_KEY` (bash). Then restart runserver."
                ),
                id="ai.W003",
            )
        )

    # Missing file, duplicates, or an encoding that makes decouple ignore it.
    if not find_env_file():
        from contribkit.settings._env import ENV_FILE

        warnings.append(
            Warning(
                "No .env file was found at the project root, so no key can "
                "be loaded.",
                hint=(
                    f"Expected {ENV_FILE}. Copy .env.example to .env, fill in "
                    "AI_GROQ_API_KEY, then restart the server."
                ),
                id="ai.W004",
            )
        )
    for dup in duplicate_keys():
        warnings.append(
            Warning(
                f"Duplicate key {dup['key']} in .env ({dup['count']} lines).",
                hint=(
                    f"python-decouple uses the LAST occurrence "
                    f"(line {dup['last_line']}). Keep exactly one "
                    f"AI_GROQ_API_KEY line and restart the server."
                ),
                id="ai.W005",
            )
        )
    for issue in config_issues():
        if issue.startswith("UTF-") or issue.startswith("unreadable"):
            warnings.append(
                Warning(
                    issue,
                    hint="Re-save the .env file as plain UTF-8 (no BOM, no "
                    "UTF-16) and restart the server.",
                    id="ai.W004",
                )
            )
    return warnings
