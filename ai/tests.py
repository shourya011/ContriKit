"""Unit tests for the AI service layer.

These tests never call a real LLM API — the HTTP layer is mocked and a fake
provider exercises the router/service contracts. All tests are
SimpleTestCase (no database access).
"""

import json
from unittest import mock

import requests
from django.test import RequestFactory, SimpleTestCase, override_settings

from ai.checks import ai_provider_credentials
from ai.services import (
    AIService,
    AIServiceError,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMInvalidResponseError,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMRouter,
    LLMTimeoutError,
    ProviderConfig,
    ToolCall,
    ToolContext,
    ToolRegistry,
    ToolSpec,
    UsageStats,
)
from ai.services import service as service_module
from ai.services.providers import PROVIDER_REGISTRY, get_provider_class
from ai.services.providers.base import LLMProvider
from ai.services.providers.groq import GroqProvider
from ai.services.tools import AITool
from ai.views import ai_health_view


class FakeProvider(LLMProvider):
    """In-memory provider for router/service contract tests."""

    name = "fake"

    def __init__(self, configured=True):
        super().__init__(ProviderConfig(name=self.name, model="fake-model"))
        self._configured = configured
        self.called = False

    def is_configured(self):
        return self._configured

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.called = True
        return ChatResponse(
            content="fake reply",
            provider=self.name,
            model=request.model or self.config.model,
            usage=UsageStats(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )


def fake_groq_response(data, status_code=200):
    response = mock.Mock(status_code=status_code)
    response.json.return_value = data
    response.text = "provider response body"
    return response


class GroqProviderRegistryTests(SimpleTestCase):
    def test_registry_contains_only_groq(self):
        self.assertEqual(set(PROVIDER_REGISTRY), {"groq"})
        self.assertIs(get_provider_class("groq"), GroqProvider)

    def test_other_vendors_are_unknown(self):
        for name in ("openai", "openai_compatible", "gemini", "anthropic", "claude"):
            with self.assertRaises(LLMConfigurationError):
                get_provider_class(name)
            self.assertNotIn(name, PROVIDER_REGISTRY)

    def test_unknown_provider_raises_config_error(self):
        with self.assertRaises(LLMConfigurationError):
            get_provider_class("does-not-exist")


class RouterTests(SimpleTestCase):
    def test_router_selects_first_configured_provider(self):
        unconfigured = FakeProvider(configured=False)
        active = FakeProvider(configured=True)
        router = LLMRouter([unconfigured, active])

        response = router.chat(ChatRequest(messages=(ChatMessage("user", "hi"),)))

        self.assertEqual(response.content, "fake reply")
        self.assertFalse(unconfigured.called)
        self.assertTrue(active.called)

    def test_router_uses_first_provider_when_configured(self):
        provider = FakeProvider(configured=True)
        router = LLMRouter([provider])

        response = router.chat(ChatRequest(messages=(ChatMessage("user", "hi"),)))

        self.assertEqual(response.provider, "fake")
        self.assertTrue(provider.called)

    def test_router_raises_when_no_provider_configured(self):
        router = LLMRouter([FakeProvider(configured=False)])
        with self.assertRaises(LLMConfigurationError):
            router.chat(ChatRequest(messages=(ChatMessage("user", "hi"),)))

    def test_health_reports_configured_state(self):
        router = LLMRouter([FakeProvider(configured=False), FakeProvider(configured=True)])
        health = router.health()
        self.assertEqual(health[0]["configured"], False)
        self.assertEqual(health[1]["configured"], True)


class GroqProviderTests(SimpleTestCase):
    def setUp(self):
        self.provider = GroqProvider(
            ProviderConfig(
                name="groq",
                api_key="gsk-test-super-secret-key",
                base_url="https://api.groq.com/openai/v1",
                model="llama-3.3-70b-versatile",
                timeout=5,
                max_tokens=64,
                temperature=0.3,
            )
        )
        self.request = ChatRequest(
            messages=(
                ChatMessage(role="system", content="be helpful"),
                ChatMessage(role="user", content="hello"),
            )
        )

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_sends_request_with_expected_payload(self, mock_post):
        mock_post.return_value = fake_groq_response(
            {
                "model": "llama-3.3-70b-versatile",
                "choices": [{"message": {"content": "Hi there!"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            }
        )

        response = self.provider.chat(self.request)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        payload = call_kwargs["json"]
        self.assertEqual(call_kwargs["headers"]["Authorization"], "Bearer gsk-test-super-secret-key")
        self.assertEqual(payload["model"], "llama-3.3-70b-versatile")
        self.assertEqual(payload["stream"], False)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["content"], "hello")
        self.assertEqual(response.content, "Hi there!")
        self.assertEqual(response.usage.total_tokens, 3)
        self.assertEqual(response.provider, "groq")

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_request_overrides_apply(self, mock_post):
        mock_post.return_value = fake_groq_response(
            {"model": "override-model", "choices": [{"message": {"content": "ok"}}]}
        )
        self.provider.chat(
            ChatRequest(
                messages=(ChatMessage(role="user", content="hi"),),
                model="override-model",
                temperature=0.9,
                max_tokens=999,
            )
        )
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "override-model")
        self.assertEqual(payload["temperature"], 0.9)
        self.assertEqual(payload["max_tokens"], 999)

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_timeout_raises_typed_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("timed out")
        with self.assertRaises(LLMTimeoutError):
            self.provider.chat(self.request)

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_connection_error_raises_unavailable(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("no route")
        with self.assertRaises(LLMProviderUnavailableError):
            self.provider.chat(self.request)

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_auth_error_maps_401(self, mock_post):
        mock_post.return_value = fake_groq_response({}, status_code=401)
        with self.assertRaises(LLMAuthenticationError) as ctx:
            self.provider.chat(self.request)
        self.assertIn("AI_GROQ_API_KEY", str(ctx.exception))
        self.assertIn("groq", str(ctx.exception))

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_posts_to_groq_endpoint_with_bearer_key(self, mock_post):
        mock_post.return_value = fake_groq_response(
            {
                "model": "llama-3.3-70b-versatile",
                "choices": [{"message": {"content": "Hello from Groq!"}}],
            }
        )
        response = self.provider.chat(self.request)
        called_url = mock_post.call_args.args[0]
        self.assertIn("api.groq.com", called_url)
        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer gsk-test-super-secret-key")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "llama-3.3-70b-versatile")
        self.assertEqual(response.content, "Hello from Groq!")
        self.assertEqual(response.provider, "groq")

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_rate_limit_maps_429(self, mock_post):
        mock_post.return_value = fake_groq_response({}, status_code=429)
        with self.assertRaises(LLMRateLimitError):
            self.provider.chat(self.request)

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_unknown_model_maps_404(self, mock_post):
        mock_post.return_value = fake_groq_response({}, status_code=404)
        with self.assertRaises(LLMProviderError) as ctx:
            self.provider.chat(self.request)
        self.assertEqual(ctx.exception.status_code, 404)

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_server_error_maps_5xx(self, mock_post):
        mock_post.return_value = fake_groq_response({}, status_code=500)
        with self.assertRaises(LLMProviderError):
            self.provider.chat(self.request)

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_non_json_response_raises_invalid(self, mock_post):
        response = mock.Mock(status_code=200)
        response.json.side_effect = ValueError("not json")
        response.text = "not-json"
        mock_post.return_value = response
        with self.assertRaises(LLMInvalidResponseError):
            self.provider.chat(self.request)

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_empty_content_raises_invalid(self, mock_post):
        mock_post.return_value = fake_groq_response(
            {"model": "llama-3.3-70b-versatile", "choices": [{"message": {"content": "  "}}]}
        )
        with self.assertRaises(LLMInvalidResponseError):
            self.provider.chat(self.request)

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_sends_tools_schema_in_payload(self, mock_post):
        tool = ToolSpec(
            name="search_issues",
            description="Search issues.",
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        )
        mock_post.return_value = fake_groq_response(
            {"model": "llama-3.3-70b-versatile", "choices": [{"message": {"content": "ok"}}]}
        )
        self.provider.chat(
            ChatRequest(
                messages=(ChatMessage(role="user", content="find"),),
                tools=(tool,),
            )
        )
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["tools"][0]["type"], "function")
        self.assertEqual(payload["tools"][0]["function"]["name"], "search_issues")

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_parses_tool_calls_from_response(self, mock_post):
        mock_post.return_value = fake_groq_response(
            {
                "model": "llama-3.3-70b-versatile",
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_issues",
                                        "arguments": '{"q": "python"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
            }
        )
        response = self.provider.chat(self.request)
        self.assertEqual(len(response.tool_calls), 1)
        self.assertEqual(response.tool_calls[0].name, "search_issues")
        self.assertEqual(response.tool_calls[0].arguments, {"q": "python"})
        self.assertEqual(response.finish_reason, "tool_calls")
        self.assertEqual(response.content, "")

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_malformed_tool_arguments_preserved(self, mock_post):
        mock_post.return_value = fake_groq_response(
            {
                "model": "llama-3.3-70b-versatile",
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_2",
                                    "type": "function",
                                    "function": {"name": "search_issues", "arguments": "{not json"},
                                }
                            ],
                        }
                    }
                ],
            }
        )
        response = self.provider.chat(self.request)
        self.assertIn("_malformed", response.tool_calls[0].arguments)

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_empty_response_without_tool_calls_raises(self, mock_post):
        mock_post.return_value = fake_groq_response(
            {"model": "llama-3.3-70b-versatile", "choices": [{"message": {"content": None}}]}
        )
        with self.assertRaises(LLMInvalidResponseError):
            self.provider.chat(self.request)

    def test_unconfigured_provider_raises(self):
        unconfigured = GroqProvider(ProviderConfig(name="groq", api_key=""))
        self.assertFalse(unconfigured.is_configured())
        with self.assertRaises(LLMConfigurationError):
            unconfigured.chat(self.request)


class AIServiceTests(SimpleTestCase):
    def setUp(self):
        self.router = LLMRouter([FakeProvider(configured=True)])

    def test_chat_returns_response(self):
        response = AIService(self.router).chat([ChatMessage(role="user", content="hi")])
        self.assertEqual(response.content, "fake reply")

    def test_empty_messages_raise(self):
        with self.assertRaises(AIServiceError):
            AIService(self.router).chat([])

    def test_bad_message_type_raises(self):
        with self.assertRaises(TypeError):
            AIService(self.router).chat(["not a ChatMessage"])

    def test_is_configured_and_health(self):
        service = AIService(self.router)
        self.assertTrue(service.is_configured())
        health = service.health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["active_provider"], "fake")

    def test_health_not_configured(self):
        service = AIService(LLMRouter([FakeProvider(configured=False)]))
        self.assertFalse(service.is_configured())
        self.assertEqual(service.health()["status"], "not_configured")


class EchoTool(AITool):
    """In-memory tool used to test the registry/loop without a database."""

    name = "echo"
    description = "Echo args."
    parameters = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
    }

    def run(self, context: ToolContext, value=""):
        return {"echo": value, "user": getattr(context.user, "username", None)}


class ScriptedProvider(LLMProvider):
    """Returns canned responses in order; records every request."""

    name = "scripted"

    def __init__(self, responses):
        super().__init__(ProviderConfig(name=self.name, model="fake-model"))
        self.responses = list(responses)
        self.requests: list[ChatRequest] = []

    def is_configured(self):
        return True

    def chat(self, request):
        self.requests.append(request)
        return self.responses.pop(0)


def make_registry():
    registry = ToolRegistry()
    registry.register(EchoTool())
    return registry


class ToolRegistryTests(SimpleTestCase):
    def test_executes_declared_params_only(self):
        result = make_registry().execute(
            "echo",
            {"value": "hello", "user_id": 999, "__proto__": "x"},
            ToolContext(),
        )
        self.assertEqual(result, {"echo": "hello", "user": None})

    def test_unknown_tool_returns_error(self):
        result = make_registry().execute("delete_all", {}, ToolContext())
        self.assertEqual(result["error"], "Unknown tool: 'delete_all'.")

    def test_missing_tool_argument_is_safe(self):
        result = make_registry().execute("echo", {}, ToolContext())
        self.assertEqual(result, {"echo": "", "user": None})

    def test_tool_exception_is_contained(self):
        class BrokenTool(AITool):
            name = "broken"
            description = "raises"
            parameters = {"type": "object", "properties": {}}

            def run(self, context, **kwargs):
                raise RuntimeError("boom")

        registry = ToolRegistry()
        registry.register(BrokenTool())
        result = registry.execute("broken", {}, ToolContext())
        self.assertIn("error", result)

    def test_specs_are_tool_spec_objects(self):
        specs = make_registry().specs()
        self.assertEqual(specs[0].name, "echo")
        self.assertIn("properties", specs[0].parameters)


class ToolLoopTests(SimpleTestCase):
    def test_tool_call_is_executed_and_result_fed_back(self):
        tool_call = ToolCall(id="call_1", name="echo", arguments={"value": "issue 42"})
        provider = ScriptedProvider(
            [
                ChatResponse(content="", provider="scripted", model="m", tool_calls=(tool_call,)),
                ChatResponse(content="Final answer.", provider="scripted", model="m"),
            ]
        )
        service = AIService(LLMRouter([provider]), tools=make_registry())
        response = service.chat([ChatMessage(role="user", content="tell me about x")])

        self.assertEqual(response.content, "Final answer.")
        self.assertEqual(len(provider.requests), 2)
        second_request = provider.requests[1]
        # assistant tool_call followed by the tool result message
        self.assertEqual(second_request.messages[1].role, "assistant")
        self.assertTrue(second_request.messages[1].tool_calls)
        self.assertEqual(second_request.messages[2].role, "tool")
        self.assertEqual(second_request.messages[2].tool_call_id, "call_1")
        self.assertIn("issue 42", second_request.messages[2].content)

    def test_loop_stops_after_max_rounds(self):
        def tool_call_round():
            return ChatResponse(
                content="",
                provider="scripted",
                model="m",
                tool_calls=(ToolCall(id="c", name="echo", arguments={"value": "x"}),),
            )

        provider = ScriptedProvider([tool_call_round() for _ in range(5)])
        service = AIService(LLMRouter([provider]), tools=make_registry())
        response = service.chat(
            [ChatMessage(role="user", content="loop")], max_tool_rounds=2
        )

        # 2 tool rounds + 1 forced final call (no tools)
        self.assertEqual(len(provider.requests), 3)
        self.assertEqual(provider.requests[-1].tools, ())
        self.assertEqual(response.content, "")

    def test_no_tools_single_call(self):
        provider = FakeProvider(configured=True)
        service = AIService(LLMRouter([provider]))
        response = service.chat([ChatMessage(role="user", content="hi")])
        self.assertEqual(response.content, "fake reply")


class SettingsWiringTests(SimpleTestCase):
    def tearDown(self):
        service_module._ai_service = None

    @override_settings(
        AI_PROVIDER="groq",
        AI_PROVIDERS="groq",
        AI_GROQ_API_KEY="env-test-key",
        AI_GROQ_MODEL="env-test-model",
        AI_GROQ_BASE_URL="https://api.groq.com/openai/v1",
        AI_GROQ_TIMEOUT=30,
        AI_GROQ_MAX_TOKENS=200,
        AI_GROQ_TEMPERATURE=0.5,
    )
    def test_default_router_built_from_settings(self):
        service = service_module.get_ai_service()
        self.assertTrue(service.is_configured())
        provider = service.router.providers[0]
        self.assertEqual(provider.name, "groq")
        self.assertEqual(provider.config.api_key, "env-test-key")
        self.assertEqual(provider.config.model, "env-test-model")
        self.assertEqual(provider.config.timeout, 30)
        self.assertIn("api.groq.com", provider.config.base_url)

    @override_settings(
        AI_PROVIDER="groq",
        AI_PROVIDERS="groq",
        AI_GROQ_API_KEY="env-test-key",
        AI_GROQ_MODEL="llama-3.3-70b-versatile",
    )
    def test_retired_groq_model_is_remapped(self):
        service = service_module.get_ai_service()
        self.assertEqual(service.router.providers[0].config.model, "openai/gpt-oss-120b")


class HealthViewTests(SimpleTestCase):
    def test_health_view_returns_json(self):
        service = AIService(LLMRouter([FakeProvider(configured=True)]))
        with mock.patch("ai.views.get_ai_service", return_value=service):
            request = RequestFactory().get("/ai/health/")
            response = ai_health_view(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["active_provider"], "fake")

    def test_health_view_contains_no_secrets(self):
        service = AIService(
            LLMRouter(
                [
                    GroqProvider(
                        ProviderConfig(name="groq", api_key="super-secret-key")
                    )
                ]
            )
        )
        with mock.patch("ai.views.get_ai_service", return_value=service):
            request = RequestFactory().get("/ai/health/")
            response = ai_health_view(request)
        data = json.loads(response.content)
        self.assertNotIn("super-secret-key", str(data))


class ProviderCredentialCheckTests(SimpleTestCase):
    """The startup warning that explains a silent, request-free 503.

    With no credentials the router never makes an outbound call, so the
    assistant looks broken instead of unconfigured; ``manage.py check`` /
    ``runserver`` must say so.
    """

    def setUp(self):
        # Provide a real (temp) .env with the key unset so the check only
        # reports the credential warning and not "file missing" (ai.W004).
        import tempfile
        from pathlib import Path

        from ai import env_diagnostics

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env_file = Path(tmp.name) / ".env"
        env_file.write_text("AI_GROQ_API_KEY=\n", encoding="utf-8")
        patcher = mock.patch.object(
            env_diagnostics, "find_env_file", return_value=str(env_file)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(env_diagnostics._raw_file_values.cache_clear)
        self.addCleanup(env_diagnostics._raw_entries.cache_clear)

    def test_warns_when_no_provider_has_credentials(self):
        with override_settings(
            AI_PROVIDERS="groq",
            AI_GROQ_API_KEY="",
        ):
            warnings = ai_provider_credentials(None)

        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].id, "ai.W001")
        self.assertIn("AI_GROQ_API_KEY", warnings[0].hint)
        self.assertNotIn("AI_OPENAI_API_KEY", warnings[0].hint)
        self.assertNotIn("AI_ANTHROPIC_API_KEY", warnings[0].hint)
        self.assertNotIn("AI_GEMINI_API_KEY", warnings[0].hint)
        self.assertIn("manage.py ai_test", warnings[0].hint)

    def test_silent_when_groq_has_credentials(self):
        with override_settings(
            AI_PROVIDERS="groq",
            AI_GROQ_API_KEY="gsk-configured",
        ):
            self.assertEqual(ai_provider_credentials(None), [])

    def test_removed_vendors_in_env_do_not_silence_the_warning(self):
        with override_settings(
            AI_PROVIDERS="openai,anthropic",
            AI_GROQ_API_KEY="",
        ):
            warnings = ai_provider_credentials(None)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].id, "ai.W001")

    def test_unknown_provider_names_do_not_crash_the_check(self):
        with override_settings(AI_PROVIDERS="not_a_provider", AI_GROQ_API_KEY=""):
            warnings = ai_provider_credentials(None)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].id, "ai.W001")

