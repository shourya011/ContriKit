"""Diagnostics for the .env / environment-variable configuration.

Two classic bugs make ``AI_GROQ_API_KEY`` appear "present in .env but not
configured":

1. **Environment-variable precedence** — python-decouple checks ``os.environ``
   BEFORE ``.env``. A leftover (even empty) ``AI_GROQ_API_KEY`` variable in the
   shell silently overrides the file.

2. **Wrong .env file location** — the default ``decouple.config``
   (``AutoConfig()``) guesses ``.env`` from the *caller's* module path, so a
   stray ``.env``/``settings.ini`` closer to the settings package, or a path
   quirk (Windows/OneDrive), can make it read no file at all even though
   ``.env`` sits next to ``manage.py``. ContribKit now pins ``.env`` to
   ``BASE_DIR/.env`` (``contribkit/settings/_env.py``).

This module reads the raw ``.env`` itself so ``manage.py check``,
``python manage.py ai_env``, ``python manage.py ai_test`` and ``/ai/health/``
can explain exactly which of these is happening. Values are never echoed —
only presence/absence, a short prefix, and counts.
"""

import os
from functools import lru_cache

# Keys python-decouple resolves from .env / environment.
CREDENTIAL_KEYS = ("AI_GROQ_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "AI_GROQ_MODEL")


def _mask(value: str) -> str:
    return f"{value[:4]}…" if value else ""


def _env_file_path() -> str | None:
    from contribkit.settings._env import ENV_FILE

    return str(ENV_FILE) if ENV_FILE.is_file() else None


@lru_cache(maxsize=1)
def find_env_file() -> str | None:
    """Return the pinned .env path when the file exists, else None."""
    return _env_file_path()


@lru_cache(maxsize=1)
def _raw_file_values() -> dict[str, str]:
    """Raw last-wins values from .env (as python-decouple would use them)."""
    path = find_env_file()
    if not path:
        return {}
    values = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                clean = line.strip()
                if not clean or "=" not in clean:
                    continue
                key_raw, _, value = clean.partition("=")
                key = key_raw.strip().lstrip("\ufeff")
                values[key] = value.strip().strip("'\"")
    except OSError:
        return {}
    return values


@lru_cache(maxsize=1)
def _raw_entries() -> list[dict]:
    """Every key=value occurrence in .env (masked values, line numbers)."""
    path = find_env_file()
    if not path:
        return []
    entries = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for lineno, line in enumerate(fh, start=1):
                clean = line.strip()
                if not clean or "=" not in clean:
                    continue
                has_bom = lineno == 1 and clean.startswith("\ufeff")
                key = clean.split("=", 1)[0].strip()
                if has_bom:
                    key = key.lstrip("\ufeff")
                value = clean.split("=", 1)[1].strip().strip("'\"")
                entries.append(
                    {
                        "line": lineno,
                        "key": key,
                        "bom": has_bom,
                        "masked": _mask(value),
                        "empty": not bool(value),
                    }
                )
    except OSError:
        return []
    return entries


def _encoding_notes(path: str) -> list[str]:
    """Detect encodings that break naive key/value parsing (no secrets)."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(4)
    except OSError:
        return ["unreadable"]
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return ["UTF-16 byte order mark — python-decouple cannot read this file."]
    if head[:3] == b"\xef\xbb\xbf":
        return [
            "UTF-8 BOM (EF BB BF) — the FIRST line's key gains an invisible "
            "BOM character and is silently ignored by python-decouple."
        ]
    return []


def duplicate_keys() -> list[dict]:
    """Credential keys that appear more than once in .env (last line wins)."""
    by_key: dict[str, list[dict]] = {}
    for entry in _raw_entries():
        if entry["key"] in CREDENTIAL_KEYS:
            by_key.setdefault(entry["key"], []).append(entry)
    return [
        {
            "key": key,
            "count": len(entries),
            "lines": [e["line"] for e in entries],
            "last_line": entries[-1]["line"],
            "last_value": entries[-1]["masked"],
            "message": (
                f"{key} appears {len(entries)} times (lines "
                f"{', '.join(str(e['line']) for e in entries)}). python-decouple "
                f"uses the LAST one (line {entries[-1]['line']}). Delete the "
                "duplicates — only one AI_GROQ_API_KEY line is allowed."
            ),
        }
        for key, entries in sorted(by_key.items())
        if len(entries) > 1
    ]


def env_config_conflicts() -> list[dict]:
    """Report credential keys where the OS environment overrides ``.env``.

    A key is a conflict when the OS environment defines it AND the raw
    ``.env`` defines a different value. An empty-but-present OS variable is
    the classic Windows symptom: ``AI_GROQ_API_KEY=`` in the shell shadows
    the file.
    """
    file_values = _raw_file_values()
    conflicts = []
    for key in CREDENTIAL_KEYS:
        env_var = os.environ.get(key, None)  # None when not set at all
        if env_var is None or key not in file_values:
            continue  # no override, or .env doesn't define it
        if env_var == file_values[key]:
            continue  # both agree — nothing wrong
        conflicts.append(
            {
                "key": key,
                "env_var_empty": not bool(env_var),
                "env_file_value": _mask(file_values[key]) or None,
                "env_var_value": _mask(env_var) or None,
                "message": (
                    f"{key} is {'EMPTY' if env_var == '' else 'set to ' + _mask(env_var) + '!'} "
                    f"in the OS environment, which overrides the "
                    f"'{_mask(file_values[key])}' value in .env."
                ),
            }
        )
    return conflicts


def loaded_from_environment() -> dict[str, str | None]:
    """Which credential keys actually came from the process environment."""
    return {
        key: _mask(os.environ.get(key, "")) or None
        for key in CREDENTIAL_KEYS
        if os.environ.get(key, "")
    }


def config_issues() -> list[str]:
    """Human-readable list of everything suspicious (no secrets)."""
    from contribkit.settings._env import ENV_FILE

    issues = []
    path = find_env_file()
    if not path:
        issues.append(
            "No .env file at the project root. Expected: "
            f"{ENV_FILE}. Copy .env.example to .env and add your Groq key."
        )
    else:
        issues.extend(_encoding_notes(path))
    issues.extend(dup["message"] for dup in duplicate_keys())
    issues.extend(conflict["message"] for conflict in env_config_conflicts())
    return issues


def env_health_payload() -> dict:
    """Small, secret-safe payload for /ai/health/ (and ai_env diagnostics)."""
    from contribkit.settings._env import ENV_FILE, ENV_FILE_ERROR

    path = find_env_file()
    return {
        "env_file_found": bool(path),
        "env_file": path or None,
        "expected_env_file": str(ENV_FILE),
        "env_file_error": ENV_FILE_ERROR,
        "encoding_notes": _encoding_notes(path) if path else [],
        "duplicates": duplicate_keys(),
        "conflicts": env_config_conflicts(),
        "loaded_from_environment": loaded_from_environment(),
    }
