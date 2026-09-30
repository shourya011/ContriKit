"""Tests for Groq routing: registry, retries, circuit breaker, settings wiring.

No real LLM calls: HTTP is mocked and fake providers simulate failures to
exercise priority ordering, fallback, retries/backoff, rate limiting, and the
circuit breaker. Settings wiring is tested with override_settings.
"""

from unittest import mock

import requests
from django.test import SimpleTestCase, override_settings

from ai.services import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMRouter,
    LLMTimeoutError,
    ProviderConfig,
    UsageStats,
)
from ai.services import service as service_module
from ai.services.providers import (
    PROVIDER_REGISTRY,
    available_providers,
    get_provider_class,
    get_provider_defaults,
)
from ai.services.providers.base import LLMProvider
from ai.services.providers.groq import GroqProvider


class FakeProvider(LLMProvider):
    """Configurable in-memory provider used to test router behavior."""

    def __init__(self, name="fake", configured=True, error=None, priority=100, rate_limit=None):
        super().__init__(
            ProviderConfig(
                name=name, model="fake-model", priority=priority,
                rate_limit_per_minute=rate_limit,
            )
        )
        self._configured = configured
        self.error = error
        self.calls = 0

    def is_configured(self):
        return self._configured

    def chat(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return ChatResponse(
            content=f"reply from {self.name}",
            provider=self.name,
            model="fake-model",
            usage=UsageStats(total_tokens=1),
        )


def request():
    return ChatRequest(messages=(ChatMessage(role="user", content="hi"),))


def fake_groq_response(data, status_code=200):
    response = mock.Mock(status_code=status_code)
    response.json.return_value = data
    response.text = "body"
    return response


# ── Registry / vendor defaults ────────────────────────────────────────────

class ProviderRegistryTests(SimpleTestCase):
    def test_only_groq_is_registered(self):
        self.assertEqual(set(PROVIDER_REGISTRY), {"groq"})
        self.assertIs(get_provider_class("groq"), GroqProvider)

    def test_removed_vendor_names_are_unknown(self):
        for name in ("openai", "openai_compatible", "gemini", "anthropic", "grok", "xai"):
            with self.assertRaises(LLMConfigurationError):
                get_provider_class(name)
            self.assertNotIn(name, PROVIDER_REGISTRY)

    def test_vendor_defaults_are_groq(self):
        defaults = get_provider_defaults("groq")
        self.assertIn("https://api.groq.com", defaults["base_url"])
        self.assertEqual(defaults["model"], "openai/gpt-oss-120b")
        self.assertEqual(get_provider_defaults("anthropic"), {})
        self.assertEqual(get_provider_defaults("openai"), {})

    def test_available_providers_is_just_groq(self):
        self.assertEqual(available_providers(), ("groq",))


# ── Groq HTTP provider (smoke via the registry class) ─────────────────────

class GroqProviderHttpTests(SimpleTestCase):
    def setUp(self):
        self.provider = GroqProvider(
            ProviderConfig(
                name="groq",
                api_key="gsk-test",
                base_url="https://api.groq.com/openai/v1",
                model="llama-3.3-70b-versatile",
                timeout=5,
                max_tokens=256,
                temperature=0.4,
            )
        )

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_builds_chat_completions_payload(self, mock_post):
        mock_post.return_value = fake_groq_response(
            {
                "model": "llama-3.3-70b-versatile",
                "choices": [{"message": {"content": "Hello from Groq!"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        )
        self.provider.chat(
            ChatRequest(
                messages=(
                    ChatMessage(role="system", content="be helpful"),
                    ChatMessage(role="user", content="hello"),
                )
            )
        )
        payload = mock_post.call_args.kwargs["json"]
        headers = mock_post.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer gsk-test")
        self.assertIn("api.groq.com", mock_post.call_args.args[0])
        self.assertEqual(payload["model"], "llama-3.3-70b-versatile")
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "be helpful"})
        self.assertEqual(payload["messages"][1], {"role": "user", "content": "hello"})

    @mock.patch("ai.services.providers.groq.requests.post")
    def test_timeout_maps_to_typed_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout("slow")
        with self.assertRaises(LLMTimeoutError):
            self.provider.chat(ChatRequest(messages=(ChatMessage(role="user", content="hi"),)))

    def test_unconfigured_raises(self):
        provider = GroqProvider(ProviderConfig(name="groq", api_key=""))
        self.assertFalse(provider.is_configured())
        with self.assertRaises(LLMConfigurationError):
            provider.chat(ChatRequest(messages=(ChatMessage(role="user", content="hi"),)))


# ── Router: priority, fallback, retry, rate limit, circuit breaker ────────

class RouterPriorityTests(SimpleTestCase):
    def test_lower_priority_number_tried_first(self):
        secondary = FakeProvider(name="secondary", priority=50)
        primary = FakeProvider(name="primary", priority=10)
        router = LLMRouter([secondary, primary])
        response = router.chat(request())
        self.assertEqual(response.content, "reply from primary")
        self.assertEqual(primary.calls, 1)
        self.assertEqual(secondary.calls, 0)

    def test_unconfigured_priority_provider_skipped(self):
        unconfigured = FakeProvider(name="unconfigured", configured=False, priority=1)
        configured = FakeProvider(name="configured", priority=50)
        router = LLMRouter([unconfigured, configured])
        response = router.chat(request())
        self.assertEqual(response.provider, "configured")

    def test_health_includes_priority_and_status(self):
        router = LLMRouter([FakeProvider(name="p", priority=7)])
        health = router.health()[0]
        self.assertEqual(health["priority"], 7)
        self.assertEqual(health["status"], "healthy")


class RouterFallbackTests(SimpleTestCase):
    def test_falls_back_on_timeout(self):
        primary = FakeProvider(name="primary", error=LLMTimeoutError("slow", provider="primary"))
        secondary = FakeProvider(name="secondary")
        router = LLMRouter([primary, secondary], retries=0)
        response = router.chat(request())
        self.assertEqual(response.provider, "secondary")

    def test_falls_back_on_rate_limit(self):
        primary = FakeProvider(name="primary", error=LLMRateLimitError("429", provider="primary"))
        secondary = FakeProvider(name="secondary")
        router = LLMRouter([primary, secondary], retries=0)
        self.assertEqual(router.chat(request()).provider, "secondary")

    def test_falls_back_on_auth_error(self):
        primary = FakeProvider(name="primary", error=LLMAuthenticationError("bad key", provider="primary"))
        secondary = FakeProvider(name="secondary")
        router = LLMRouter([primary, secondary], retries=0)
        self.assertEqual(router.chat(request()).provider, "secondary")

    def test_all_fail_raises_unavailable(self):
        primary = FakeProvider(name="primary", error=LLMTimeoutError("slow"))
        secondary = FakeProvider(name="secondary", error=LLMProviderUnavailableError("down"))
        router = LLMRouter([primary, secondary], retries=0)
        with self.assertRaises(LLMProviderUnavailableError):
            router.chat(request())

    def test_all_fail_preserves_concrete_error_type(self):
        # A real (bad/revoked) key must surface as an auth error, not as a
        # generic "provider unavailable" — otherwise the UI reports the model
        # as "not configured" even though a key is present.
        primary = FakeProvider(name="primary", error=LLMAuthenticationError("bad key", provider="primary"))
        router = LLMRouter([primary], retries=0)
        with self.assertRaises(LLMAuthenticationError):
            router.chat(request())

    def test_fallback_disabled_raises_original_error(self):
        primary = FakeProvider(name="primary", error=LLMTimeoutError("slow"))
        router = LLMRouter([primary], fallback=False, retries=0)
        with self.assertRaises(LLMTimeoutError):
            router.chat(request())

    def test_deterministic_4xx_not_retried_or_failed_over(self):
        primary = FakeProvider(name="primary", error=LLMProviderError("bad request", status_code=400))
        router = LLMRouter([primary], retries=5)
        with self.assertRaises(LLMProviderError):
            router.chat(request())
        self.assertEqual(primary.calls, 1)


class RouterRetryTests(SimpleTestCase):
    def test_transient_error_retried_then_succeeds(self):
        provider = FakeProvider(name="p")

        def flaky(request):
            provider.calls += 1
            if provider.calls < 3:
                raise LLMProviderUnavailableError("flaky")
            return ChatResponse(content="ok", provider="p", model="m")

        provider.chat = flaky
        router = LLMRouter([provider], retries=2, retry_backoff=0)
        self.assertEqual(router.chat(request()).content, "ok")
        self.assertEqual(provider.calls, 3)

    def test_retries_exhausted_raises(self):
        provider = FakeProvider(name="p", error=LLMTimeoutError("slow"))
        router = LLMRouter([provider], retries=2, retry_backoff=0)
        with self.assertRaises(LLMTimeoutError):
            router.chat(request())
        self.assertEqual(provider.calls, 3)  # 1 initial + 2 retries


class RouterRateLimitTests(SimpleTestCase):
    def test_rate_limit_skips_provider(self):
        provider = FakeProvider(name="limited", rate_limit=1)
        router = LLMRouter([provider], retries=0)
        router.chat(request())  # first attempt consumes the single slot
        with self.assertRaises(LLMProviderUnavailableError):
            router.chat(request())  # second attempt is blocked
        self.assertEqual(provider.calls, 1)


class RouterCircuitBreakerTests(SimpleTestCase):
    def test_breaker_opens_after_failures(self):
        provider = FakeProvider(name="p", error=LLMProviderUnavailableError("down"))
        router = LLMRouter([provider], retries=0, circuit_failure_threshold=2,
                           circuit_reset_seconds=60)
        with self.assertRaises(LLMProviderUnavailableError):
            router.chat(request())
        with self.assertRaises(LLMProviderUnavailableError):
            router.chat(request())
        # Breaker now open: the third request should not even call the provider.
        provider.error = None
        with self.assertRaises(LLMProviderUnavailableError):
            router.chat(request())
        self.assertEqual(provider.calls, 2)

    def test_breaker_resets_after_window(self):
        provider = FakeProvider(name="p", error=LLMProviderUnavailableError("down"))
        router = LLMRouter([provider], retries=0, circuit_failure_threshold=1,
                           circuit_reset_seconds=0)
        with self.assertRaises(LLMProviderUnavailableError):
            router.chat(request())
        provider.error = None
        self.assertEqual(router.chat(request()).provider, "p")


# ── Settings wiring: Groq only ────────────────────────────────────────────

class SettingsGroqProviderTests(SimpleTestCase):
    def tearDown(self):
        service_module._ai_service = None

    @override_settings(
        AI_PROVIDERS="groq",
        AI_GROQ_API_KEY="gsk-test",
        AI_GROQ_MODEL="llama-custom",
    )
    def test_builds_groq_from_settings(self):
        router = service_module.build_default_router()
        self.assertEqual([p.name for p in router.providers], ["groq"])
        self.assertTrue(router.fallback)
        self.assertEqual(router.retries, 2)
        groq = router.providers[0]
        self.assertEqual(groq.config.api_key, "gsk-test")
        self.assertEqual(groq.config.model, "llama-custom")
        self.assertIn("api.groq.com", groq.config.base_url)

    @override_settings(AI_PROVIDERS="", AI_PROVIDER="groq", AI_GROQ_API_KEY="key")
    def test_legacy_single_provider_still_works(self):
        router = service_module.build_default_router()
        self.assertEqual([p.name for p in router.providers], ["groq"])
        self.assertTrue(router.providers[0].is_configured())

    @override_settings(
        AI_PROVIDERS="openai,anthropic,gemini,grok",
        AI_GROQ_API_KEY="gsk-test",
    )
    def test_removed_vendor_names_fall_back_to_groq(self):
        # Old .env files may still list openai/anthropic/gemini. Those names
        # are dropped and Groq is used instead.
        router = service_module.build_default_router()
        self.assertEqual([p.name for p in router.providers], ["groq"])
        self.assertTrue(router.providers[0].is_configured())

    @override_settings(
        AI_PROVIDERS="groq,openai,anthropic",
        AI_GROQ_API_KEY="gsk-test",
    )
    def test_mixed_list_keeps_only_groq(self):
        router = service_module.build_default_router()
        self.assertEqual([p.name for p in router.providers], ["groq"])
        self.assertTrue(router.providers[0].is_configured())
        self.assertIn("api.groq.com", router.providers[0].config.base_url)
        health = router.health()[0]
        self.assertEqual(health["provider"], "groq")
        self.assertEqual(health["status"], "healthy")

    @override_settings(
        AI_PROVIDERS="groq",
        AI_GROQ_API_KEY="gsk-test",
        AI_PROVIDER_RETRIES=3,
        AI_PROVIDER_RETRY_BACKOFF=0.1,
    )
    def test_service_uses_groq(self):
        service = service_module.get_ai_service()
        self.assertTrue(service.is_configured())
        self.assertEqual(service.router.retries, 3)
        health = service.health()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["active_provider"], "groq")
        self.assertTrue(health["extensions"]["fallback"])
        self.assertTrue(health["extensions"]["circuit_breaker"])
