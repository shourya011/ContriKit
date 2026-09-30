"""Full diagnostic for "the key is in .env but the app says not configured".

Prints (never the secret itself, only masked prefixes):

    - python / decouple versions and the project root
    - the exact .env path Django is pinned to, and whether it exists
    - encoding problems (UTF-8 BOM, UTF-16) and duplicate keys
    - what the .env file contains for the AI keys (masked)
    - what the OS environment contains for the same keys (masked)
    - what Django actually loaded into settings
    - a verdict with the exact fix

Usage:
    python manage.py ai_env
"""

import os
import platform
import sys

from django.conf import settings
from django.core.management.base import BaseCommand

from ai.env_diagnostics import (
    _mask,
    _raw_entries,
    config_issues,
    duplicate_keys,
    env_config_conflicts,
    find_env_file,
    loaded_from_environment,
)


class Command(BaseCommand):
    help = "Diagnose why AI_GROQ_API_KEY is not loaded from .env (no secrets printed)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Also print every key found in .env (values stay masked).",
        )

    def handle(self, *args, **options):
        verbose = options.get("verbose", False)
        out = self.stdout.write

        from contribkit.settings._env import ENV_FILE, ENV_FILE_ERROR

        out("─" * 64)
        out("ContribKit AI environment diagnostic")
        out("─" * 64)
        out(f"Python            : {sys.version.split()[0]} ({platform.system()})")
        out(f"Settings module   : {settings.SETTINGS_MODULE}")
        out(f"Project root      : {settings.BASE_DIR}")
        out(f"Expected .env     : {ENV_FILE}")
        out(f".env file found   : {'YES' if find_env_file() else 'NO'}")

        if ENV_FILE_ERROR:
            out(self.style.ERROR(f".env parse error : {ENV_FILE_ERROR}"))

        if verbose and find_env_file():
            out("")
            out("Keys in .env (values masked):")
            for entry in _raw_entries():
                if entry["key"] in (
                    "AI_GROQ_API_KEY",
                    "AI_GROQ_MODEL",
                    "AI_GROQ_BASE_URL",
                    "SECRET_KEY",
                ):
                    out(
                        f"  line {entry['line']:>3}: {entry['key']} = "
                        f"{entry['masked'] or 'EMPTY'}"
                        + ("  ← BOM-prefixed, ignored!" if entry["bom"] else "")
                    )

        dups = duplicate_keys()
        if dups:
            out(self.style.WARNING(""))
            for dup in dups:
                out(self.style.WARNING("DUPLICATE  " + dup["message"]))

        conflicts = env_config_conflicts()
        loaded = loaded_from_environment()
        if conflicts:
            out(self.style.WARNING(""))
            for item in conflicts:
                out(self.style.WARNING("CONFLICT   " + item["message"]))

        out("")
        out("OS environment (for the same keys, masked):")
        for key in ("AI_GROQ_API_KEY", "AI_GROQ_MODEL", "GROQ_API_KEY", "OPENAI_API_KEY"):
            value = os.environ.get(key)
            if value is None:
                out(f"  {key:<24}: not set")
            elif value == "":
                out(self.style.ERROR(f"  {key:<24}: EMPTY  ← this overrides .env!"))
            else:
                out(f"  {key:<24}: {_mask(value)}")

        out("")
        out("What Django loaded (settings):")
        loaded_key = getattr(settings, "AI_GROQ_API_KEY", "") or ""
        out(
            f"  settings.AI_GROQ_API_KEY = "
            f"{_mask(loaded_key) if loaded_key else 'EMPTY (not configured)'}"
        )
        out(f"  settings.AI_GROQ_MODEL   = {getattr(settings, 'AI_GROQ_MODEL', '?')}")

        out("")
        issues = config_issues()
        if issues:
            out(self.style.WARNING("Findings:"))
            for issue in issues:
                out(self.style.WARNING("  • " + issue))
        else:
            loaded_ok = bool(loaded_key)
            if loaded_ok:
                out(self.style.SUCCESS("Verdict: configuration looks OK — the key is loaded."))
            else:
                out(
                    "Verdict: .env exists and parses, but Django still loads an "
                    "empty key. The OS environment above (EMPTY entries) or a "
                    "stale running process is the cause. Open a NEW terminal "
                    "and start the server again."
                )
        out("─" * 64)
