"""Tests for the chatbot view, session state, and source-link building.

The LLM is always mocked; the goal is to verify auth, validation, rate
limiting, session history, error mapping, and safe source resolution.
"""

import json
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from ai.services import (
    AIServiceError,
    ChatResponse,
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMProviderServerError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
    UsageStats,
)
from ai.views import _build_sources
from issues.models import Issue
from repos.models import Repo

User = get_user_model()


def fake_reply(message=None, **kwargs):
    return ChatResponse(
        content="Hello from the assistant!",
        provider="groq",
        model="openai/gpt-oss-120b",
        usage=UsageStats(prompt_tokens=5, completion_tokens=9, total_tokens=14),
    )


class ChatEndpointTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="chatter", password="pw")
        self.client = Client()

    def post_json(self, payload, **extra):
        return self.client.post(
            "/ai/chat/",
            data=json.dumps(payload),
            content_type="application/json",
            **extra,
        )

    # ── Http / auth ──────────────────────────────────────────────────
    def test_get_method_not_allowed(self):
        self.assertEqual(self.client.get("/ai/chat/").status_code, 405)

    def test_anonymous_returns_login_required_json(self):
        response = self.post_json({"message": "hi"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content)["error"], "login_required")

    # ── Validation ────────────────────────────────────────────────────
    def test_invalid_json_returns_400(self):
        self.client.force_login(self.user)
        response = self.client.post(
            "/ai/chat/", data="{not json", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["code"], "invalid_json")

    def test_empty_message_returns_400(self):
        self.client.force_login(self.user)
        response = self.post_json({"message": "   "})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["code"], "empty_message")

    @override_settings(AI_CHAT_MAX_MESSAGE_LENGTH=10)
    def test_message_too_long_returns_400(self):
        self.client.force_login(self.user)
        response = self.post_json({"message": "a" * 11})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)["code"], "message_too_long")

    # ── Success + server-side context ────────────────────────────────
    @mock.patch("ai.views.ai_assistant_chat", side_effect=fake_reply)
    def test_success_returns_reply(self, mock_chat):
        self.client.force_login(self.user)
        response = self.post_json({"message": "Find me issues"})
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["reply"], "Hello from the assistant!")
        self.assertEqual(data["provider"], "groq")
        self.assertEqual(data["model"], "openai/gpt-oss-120b")

        kwargs = mock_chat.call_args.kwargs
        self.assertEqual(kwargs["user"].username, "chatter")
        self.assertEqual(kwargs["page_path"], "/ai/chat/")
        self.assertEqual(kwargs["history"], [])
        self.assertIsInstance(kwargs["tool_events"], list)

    @mock.patch("ai.views.ai_assistant_chat", side_effect=fake_reply)
    def test_history_is_kept_between_turns(self, mock_chat):
        self.client.force_login(self.user)
        seen_histories = []

        def capture(message, **kwargs):
            seen_histories.append(list(kwargs["history"]))
            return fake_reply()

        mock_chat.side_effect = capture

        self.post_json({"message": "first question"})
        self.post_json({"message": "second question"})

        self.assertEqual(len(seen_histories), 2)
        self.assertEqual(seen_histories[0], [])
        self.assertEqual(len(seen_histories[1]), 2)
        self.assertEqual(seen_histories[1][0].role, "user")
        self.assertEqual(seen_histories[1][0].content, "first question")
        self.assertEqual(seen_histories[1][1].role, "assistant")

    @mock.patch("ai.views.ai_assistant_chat", side_effect=fake_reply)
    def test_sources_derived_from_tool_events(self, mock_chat):
        self.client.force_login(self.user)

        def with_events(message, **kwargs):
            kwargs["tool_events"].append(
                {
                    "name": "search_issues",
                    "result": {
                        "results": [
                            {"issue": {"id": 7, "title": "Fix typo in docs"}}
                        ]
                    },
                }
            )
            kwargs["tool_events"].append(
                {
                    "name": "search_git_commands",
                    "result": {"results": [{"command": "git checkout -b x"}]},
                }
            )
            return fake_reply()

        mock_chat.side_effect = with_events
        response = self.post_json({"message": "find issues"})
        sources = json.loads(response.content)["sources"]
        self.assertEqual(
            sources,
            [
                {"type": "issue", "label": "Fix typo in docs", "url": "/issues/7/"},
                {"type": "cheatsheet", "label": "Git Cheat Sheet", "url": "/cheatsheet/"},
            ],
        )

    # ── Rate limiting ─────────────────────────────────────────────────
    @override_settings(AI_CHAT_RATE_LIMIT=1, AI_CHAT_RATE_WINDOW=60)
    @mock.patch("ai.views.ai_assistant_chat", side_effect=fake_reply)
    def test_rate_limit_blocks_second_request(self, mock_chat):
        self.client.force_login(self.user)
        self.assertEqual(self.post_json({"message": "one"}).status_code, 200)
        second = self.post_json({"message": "two"})
        self.assertEqual(second.status_code, 429)
        self.assertEqual(json.loads(second.content)["code"], "rate_limited")

    # ── Error mapping ─────────────────────────────────────────────────
    @mock.patch("ai.views.ai_assistant_chat", side_effect=LLMProviderUnavailableError("down"))
    def test_unavailable_maps_to_503(self, mock_chat):
        self.client.force_login(self.user)
        response = self.post_json({"message": "hi"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["code"], "ai_unavailable")

    @mock.patch(
        "ai.views.ai_assistant_chat",
        side_effect=LLMConfigurationError("no key"),
    )
    def test_unconfigured_maps_to_503_with_hint(self, mock_chat):
        """No credentials: report a config problem and name the env var."""
        self.client.force_login(self.user)
        response = self.post_json({"message": "hi"})
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(data["code"], "ai_not_configured")
        self.assertIn("AI_GROQ_API_KEY", data["error"])
        self.assertEqual(data["hint"], "AI_GROQ_API_KEY")

    @mock.patch(
        "ai.views.ai_assistant_chat",
        side_effect=LLMAuthenticationError("401 bad key"),
    )
    def test_auth_failure_maps_to_503(self, mock_chat):
        """A key IS set but Groq rejects it — must not say 'not configured'."""
        self.client.force_login(self.user)
        response = self.post_json({"message": "hi"})
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(data["code"], "provider_auth_failed")
        self.assertIn("AI_GROQ_API_KEY", data["error"])
        self.assertNotIn("not configured", data["error"])

    @mock.patch(
        "ai.views.ai_assistant_chat",
        side_effect=LLMProviderServerError("500"),
    )
    def test_provider_server_error_maps_to_503(self, mock_chat):
        self.client.force_login(self.user)
        response = self.post_json({"message": "hi"})
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(data["code"], "provider_error")

    @mock.patch(
        "ai.views.ai_assistant_chat",
        side_effect=LLMRateLimitError("429"),
    )
    def test_rate_limit_maps_to_429(self, mock_chat):
        self.client.force_login(self.user)
        response = self.post_json({"message": "hi"})
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(data["code"], "provider_rate_limited")

    @mock.patch("ai.views.ai_assistant_chat", side_effect=LLMTimeoutError("slow"))
    def test_timeout_maps_to_504(self, mock_chat):
        self.client.force_login(self.user)
        response = self.post_json({"message": "hi"})
        self.assertEqual(response.status_code, 504)
        self.assertEqual(json.loads(response.content)["code"], "ai_timeout")

    @mock.patch(
        "ai.views.ai_assistant_chat",
        side_effect=LLMProviderError("model not found", status_code=404, provider="groq"),
    )
    def test_provider_client_error_maps_to_503(self, mock_chat):
        self.client.force_login(self.user)
        response = self.post_json({"message": "hi"})
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(data["code"], "provider_error")
        self.assertNotIn("gsk_", data["error"])

    @mock.patch(
        "ai.views.ai_assistant_chat",
        side_effect=LLMInvalidResponseError("empty content"),
    )
    def test_invalid_response_maps_to_503(self, mock_chat):
        self.client.force_login(self.user)
        response = self.post_json({"message": "hi"})
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(data["code"], "provider_error")

    @mock.patch("ai.views.ai_assistant_chat", side_effect=AIServiceError("boom"))
    def test_generic_failure_maps_to_500(self, mock_chat):
        self.client.force_login(self.user)
        response = self.post_json({"message": "hi"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(json.loads(response.content)["code"], "ai_error")

    @mock.patch("ai.views.ai_assistant_chat", side_effect=fake_reply)
    def test_failure_does_not_store_history(self, mock_chat):
        """A failed turn must not be persisted as a user/assistant pair."""
        self.client.force_login(self.user)
        mock_chat.side_effect = AIServiceError("boom")
        self.post_json({"message": "will fail"})
        mock_chat.side_effect = fake_reply
        response = self.post_json({"message": "after fail"})
        self.assertEqual(response.status_code, 200)
        # Only the successful turn's pair should exist.
        self.assertEqual(len(mock_chat.call_args_list), 2)
        self.assertEqual(len(mock_chat.call_args_list[1].kwargs["history"]), 0)


class ChatCsrfTests(TestCase):
    """/ai/chat/ must be reachable with the token base.html publishes.

    Regression: the widget read the token from the ``csrftoken`` cookie only,
    and no page ever issued that cookie, so the browser redirected to the
    login page and never sent a request at all. This runs the real
    ``CsrfViewMiddleware`` (``enforce_csrf_checks=True``) with a token scraped
    from the rendered landing page — the exact value the widget sends.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(username="csrf_chatter", password="pw")

    def test_chat_succeeds_with_the_token_from_the_page(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        client.cookies.pop("csrftoken", None)  # never been issued a CSRF cookie

        page = client.get("/").content.decode()
        match = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
        self.assertIsNotNone(match, "landing page published no csrf-token meta tag")

        with mock.patch("ai.views.ai_assistant_chat", side_effect=fake_reply):
            response = client.post(
                "/ai/chat/",
                data=json.dumps({"message": "How do I create a branch?"}),
                content_type="application/json",
                HTTP_X_CSRFTOKEN=match.group(1),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["reply"], "Hello from the assistant!")


class BuildSourcesTests(TestCase):
    def test_issue_template_cheatsheet_github_sources(self):
        events = [
            {"name": "get_issue_details", "result": {"issue": {"id": 3, "title": "A"}}},
            {"name": "get_template", "result": {"template": {"slug": "pr-template", "title": "PR"}}},
            {"name": "search_git_commands", "result": {"results": [{"command": "x"}]}},
            {"name": "get_github_repository", "result": {"repository": {"full_name": "a/b", "html_url": "https://github.com/a/b"}}},
        ]
        sources = _build_sources(events)
        self.assertEqual(len(sources), 4)
        self.assertEqual(sources[0]["type"], "issue")
        self.assertEqual(sources[0]["url"], "/issues/3/")
        self.assertEqual(sources[1]["type"], "template")
        self.assertEqual(sources[1]["url"], "/templates/pr-template/")
        self.assertEqual(sources[3]["type"], "github")

    def test_errors_and_unknown_tools_are_skipped(self):
        events = [
            {"name": "search_issues", "result": {"error": "boom"}},
            {"name": "delete_everything", "result": {}},
            {"name": "get_current_issue_context", "result": {"available": False}},
        ]
        self.assertEqual(_build_sources(events), [])

    def test_dedupe_and_cap(self):
        events = [
            {"name": "get_issue_details", "result": {"issue": {"id": 1, "title": "Same"}}},
            {"name": "get_issue_details", "result": {"issue": {"id": 1, "title": "Same"}}},
        ]
        self.assertEqual(len(_build_sources(events)), 1)

        many = [
            {"name": "search_issues", "result": {"results": [{"issue": {"id": i, "title": f"I{i}"}} for i in range(20)]}}
        ]
        self.assertEqual(len(_build_sources(many)), 6)


class WidgetRenderTests(TestCase):
    """The widget is included globally in base.html without breaking pages."""

    @classmethod
    def setUpTestData(cls):
        cls.editor = User.objects.create_user(username="widget_editor", password="pw")
        cls.repo = Repo.objects.create(
            editor=cls.editor,
            github_url="https://github.com/django/django",
            name="django/django",
            language="Python",
        )
        cls.issue = Issue.objects.create(
            repo=cls.repo,
            posted_by=cls.editor,
            title="Fix typo in docs",
            description="Fix a typo.",
            github_issue_url="https://github.com/django/django/issues/1",
            difficulty="beginner",
            estimated_hours=1.0,
            status="open",
        )

    def test_landing_page_renders_widget(self):
        response = self.client.get("/")
        self.assertContains(response, 'id="aiChat"')
        self.assertContains(response, "AI Contribution Assistant")
        self.assertContains(response, "/static/js/ai_chat.js")
        self.assertContains(response, "/static/css/components/chat.css")
        self.assertEqual(response.status_code, 200)

    def test_issue_page_renders_widget_with_context_chip(self):
        response = self.client.get(f"/issues/{self.issue.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="aiChat"')
        # The issue-aware suggestion chip is only rendered on issue pages.
        self.assertContains(response, "How should I approach this issue?")
        # Issue page itself is intact.
        self.assertContains(response, "Fix typo in docs")
