"""CLI smoke test for the AI service layer.

Sends one message through the full pipeline (AIService → LLMRouter →
GroqProvider) without any UI or database. Useful for verifying the Groq
key before using the chat widget.

Usage:
    python manage.py ai_test "What is a good first issue for a beginner?"
    python manage.py ai_test "Explain how git rebase works" --model openai/gpt-oss-120b
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ai.env_diagnostics import (
    config_issues,
    duplicate_keys,
    env_config_conflicts,
    find_env_file,
)
from ai.services import (
    AIServiceError,
    ChatMessage,
    LLMAuthenticationError,
    get_ai_service,
)

DEFAULT_TEST_MESSAGE = (
    "You are testing the ContribKit AI service. Reply with a short, "
    "friendly confirmation that you are operational."
)


class Command(BaseCommand):
    help = "Send a single test message to Groq (no UI/DB required)."

    def add_arguments(self, parser):
        parser.add_argument(
            "message",
            nargs="?",
            default=None,
            help="Message to send. Defaults to a connectivity test prompt.",
        )
        parser.add_argument(
            "--model",
            default=None,
            help="Override the model (defaults to the AI_GROQ_MODEL setting).",
        )
        parser.add_argument(
            "--temperature",
            type=float,
            default=None,
            help="Override temperature (defaults to AI_GROQ_TEMPERATURE).",
        )
        parser.add_argument(
            "--max-tokens",
            type=int,
            default=None,
            help="Override max response tokens (defaults to AI_GROQ_MAX_TOKENS).",
        )

    def handle(self, *args, **options):
        service = get_ai_service()

        # Show what the server actually loaded (never reveal the key itself).
        key = getattr(settings, "AI_GROQ_API_KEY", "") or ""
        model = getattr(settings, "AI_GROQ_MODEL", "openai/gpt-oss-120b")
        self.stdout.write(
            f"Groq key  : {'set (' + key[:4] + '…)' if key else 'MISSING — set AI_GROQ_API_KEY in .env (see .env.example)'}"
        )
        self.stdout.write(f"Model     : {model}")
        self.stdout.write(f".env file : {find_env_file() or 'NOT FOUND'}")

        # The gotcha: an environment variable shadows .env in python-decouple.
        for conflict in env_config_conflicts():
            self.stdout.write(
                self.style.ERROR(
                    "CONFLICT: " + conflict["message"]
                )
            )
            self.stdout.write(
                self.style.ERROR(
                    "   Fix: open a NEW terminal and unset the variable "
                    f"(`Remove-Item Env:{conflict['key']}` in PowerShell, "
                    f"`unset {conflict['key']}` in bash), then restart runserver."
                )
            )

        # Duplicate keys / unreadable encodings also produce silent failures.
        for dup in duplicate_keys():
            self.stdout.write(self.style.ERROR("DUPLICATE: " + dup["message"]))
        for issue in config_issues():
            if issue.startswith("UTF-") or issue.startswith("unreadable"):
                self.stdout.write(self.style.ERROR("ENCODING: " + issue))

        if key and env_config_conflicts():
            raise CommandError(
                "The running process loaded a value from the OS environment "
                "instead of .env. Unset the environment variable in a fresh "
                "terminal and restart the server, then re-run "
                "`python manage.py ai_test`."
            )

        if not service.is_configured():
            raise CommandError(
                "AI is not configured: Groq has no credentials. "
                "Set AI_GROQ_API_KEY in your environment / .env file, then "
                "restart the server (a running process keeps the old settings "
                "until it is restarted). If the key IS in .env, run "
                "`python manage.py ai_env` — it shows exactly what Django "
                "reads and why the key isn't loaded."
            )

        message = options["message"] or DEFAULT_TEST_MESSAGE
        messages = [
            ChatMessage(role="system", content="You are ContribKit's AI assistant."),
            ChatMessage(role="user", content=message),
        ]

        self.stdout.write(self.style.WARNING("Sending test message to Groq..."))
        try:
            response = service.chat(
                messages,
                model=options["model"],
                temperature=options["temperature"],
                max_tokens=options["max_tokens"],
            )
        except LLMAuthenticationError:
            raise CommandError(
                "AI request failed: Groq rejected the API key (HTTP 401/403). "
                "Check AI_GROQ_API_KEY in .env — keys start with gsk_. If the "
                "key is new, make sure it is active at console.groq.com."
            )
        except AIServiceError as exc:
            raise CommandError(f"AI request failed: {exc}")

        self.stdout.write(self.style.SUCCESS("✓ AI request completed"))
        self.stdout.write(f"Provider : {response.provider}")
        self.stdout.write(f"Model    : {response.model}")
        if response.usage:
            self.stdout.write(
                "Usage    : prompt={} completion={} total={}".format(
                    response.usage.prompt_tokens,
                    response.usage.completion_tokens,
                    response.usage.total_tokens,
                )
            )
        self.stdout.write("")
        self.stdout.write(response.content)
