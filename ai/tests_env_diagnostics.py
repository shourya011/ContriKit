"""Tests for AI environment/.env diagnostics.

The goal: when a user's ``.env`` has a Groq key but Django still says "not
configured", the causes to distinguish are:

- a leftover (often EMPTY) OS environment variable shadows ``.env``;
- the ``.env`` file is missing, has a BOM/encoding problem, or the key is
  duplicated (last line wins in python-decouple).
"""

import os
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from ai import env_diagnostics
from ai.checks import ai_provider_credentials


class EnvDiagnosticsTests(SimpleTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env_file = Path(self.tmpdir.name) / ".env"
        patcher = mock.patch.object(
            env_diagnostics, "find_env_file", return_value=str(self.env_file)
        )
        self.mock_find = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(env_diagnostics._raw_file_values.cache_clear)
        self.addCleanup(env_diagnostics._raw_entries.cache_clear)

    def write_env(self, content: str, encoding: str = "utf-8"):
        self.env_file.write_text(content, encoding=encoding)
        env_diagnostics._raw_file_values.cache_clear()
        env_diagnostics._raw_entries.cache_clear()

    def test_no_env_file_means_no_conflicts_and_reports_missing(self):
        self.mock_find.return_value = None
        env_diagnostics._raw_file_values.cache_clear()
        self.assertEqual(env_diagnostics.env_config_conflicts(), [])
        self.assertTrue(any("No .env file" in i for i in env_diagnostics.config_issues()))

    def test_env_var_agrees_with_env_file_is_no_conflict(self):
        self.write_env("AI_GROQ_API_KEY=gsk_same\n")
        with mock.patch.dict(os.environ, {"AI_GROQ_API_KEY": "gsk_same"}, clear=False):
            env_diagnostics._raw_file_values.cache_clear()
            self.assertEqual(env_diagnostics.env_config_conflicts(), [])

    def test_empty_env_var_overrides_env_file(self):
        """The classic PowerShell symptom: AI_GROQ_API_KEY='' in the OS
        environment shadows a valid key in .env."""
        self.write_env("AI_GROQ_API_KEY=gsk_REALKEY1234567890\n")
        with mock.patch.dict(os.environ, {"AI_GROQ_API_KEY": ""}, clear=False):
            env_diagnostics._raw_file_values.cache_clear()
            conflicts = env_diagnostics.env_config_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["key"], "AI_GROQ_API_KEY")
        self.assertTrue(conflicts[0]["env_var_empty"])
        self.assertEqual(conflicts[0]["env_file_value"], "gsk_…")

    def test_wrong_env_var_value_is_reported(self):
        self.write_env("AI_GROQ_API_KEY=gsk_FROMFILE\n")
        with mock.patch.dict(os.environ, {"AI_GROQ_API_KEY": "gsk_FROMENV"}, clear=False):
            env_diagnostics._raw_file_values.cache_clear()
            conflicts = env_diagnostics.env_config_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertFalse(conflicts[0]["env_var_empty"])
        self.assertIn("overrides", conflicts[0]["message"])

    def test_duplicate_key_detected_last_line_wins(self):
        self.write_env(
            "AI_GROQ_API_KEY=\n"
            "AI_GROQ_API_KEY=gsk_REALKEY1234567890\n"
        )
        dups = env_diagnostics.duplicate_keys()
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["key"], "AI_GROQ_API_KEY")
        self.assertEqual(dups[0]["count"], 2)
        self.assertEqual(dups[0]["last_line"], 2)
        # Decouple semantics: last occurrence wins -> the real key is used.
        self.assertEqual(
            env_diagnostics._raw_file_values().get("AI_GROQ_API_KEY"),
            "gsk_REALKEY1234567890",
        )

    def test_utf8_bom_is_detected(self):
        self.write_env("\ufeffAI_GROQ_API_KEY=gsk_REALKEY1234567890\n")
        notes = env_diagnostics._encoding_notes(str(self.env_file))
        self.assertTrue(any("BOM" in note for note in notes))
        # The BOM-prefixed first line must be flagged so users see it.
        entry = env_diagnostics._raw_entries()[0]
        self.assertTrue(entry["bom"])

    def test_utf16_is_detected(self):
        raw = "AI_GROQ_API_KEY=gsk_REALKEY1234567890\n".encode("utf-16-le")
        self.env_file.write_bytes(b"\xff\xfe" + raw)
        notes = env_diagnostics._encoding_notes(str(self.env_file))
        self.assertTrue(any("UTF-16" in note for note in notes))

    def test_payload_contains_no_secrets(self):
        self.write_env("AI_GROQ_API_KEY=gsk_SECRETKEY_123\n")
        with mock.patch.dict(os.environ, {"AI_GROQ_API_KEY": ""}, clear=False):
            env_diagnostics._raw_file_values.cache_clear()
            payload = env_diagnostics.env_health_payload()
        self.assertNotIn("SECRETKEY", str(payload))
        self.assertTrue(payload["env_file_found"])
        self.assertEqual(len(payload["conflicts"]), 1)


class ProviderCredentialCheckEnvTests(SimpleTestCase):
    """System check must explain the configuration problems."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.env_file = Path(self.tmpdir.name) / ".env"
        patcher = mock.patch.object(
            env_diagnostics, "find_env_file", return_value=str(self.env_file)
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(env_diagnostics._raw_file_values.cache_clear)
        self.addCleanup(env_diagnostics._raw_entries.cache_clear)

    def write_env(self, content: str):
        self.env_file.write_text(content, encoding="utf-8")
        env_diagnostics._raw_file_values.cache_clear()
        env_diagnostics._raw_entries.cache_clear()

    def test_w002_reported_when_env_var_overrides_env_file(self):
        self.write_env("AI_GROQ_API_KEY=gsk_FROMFILE\n")
        with mock.patch.dict(os.environ, {"AI_GROQ_API_KEY": "gsk_FROMENV"}, clear=False):
            env_diagnostics._raw_file_values.cache_clear()
            with override_settings(AI_PROVIDERS="groq", AI_GROQ_API_KEY="gsk_FROMENV"):
                warnings = ai_provider_credentials(None)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].id, "ai.W002")
        self.assertIn("AI_GROQ_API_KEY", warnings[0].hint)

    def test_w001_and_w003_reported_when_empty_env_shadows_key(self):
        self.write_env("AI_GROQ_API_KEY=gsk_FROMFILE\n")
        with mock.patch.dict(os.environ, {"AI_GROQ_API_KEY": ""}, clear=False):
            env_diagnostics._raw_file_values.cache_clear()
            with override_settings(AI_PROVIDERS="groq", AI_GROQ_API_KEY=""):
                warnings = ai_provider_credentials(None)
        ids = {w.id for w in warnings}
        self.assertEqual(ids, {"ai.W001", "ai.W003"})
        self.assertIn("AI_GROQ_API_KEY", warnings[0].hint)

    def test_w005_reported_for_duplicate_key(self):
        self.write_env(
            "AI_GROQ_API_KEY=gsk_FROMFILE\n"
            "AI_GROQ_API_KEY=\n"
        )
        with override_settings(AI_PROVIDERS="groq", AI_GROQ_API_KEY=""):
            warnings = ai_provider_credentials(None)
        self.assertIn("ai.W005", {w.id for w in warnings})

    def test_silent_when_env_file_and_env_agree_and_key_set(self):
        self.write_env("AI_GROQ_API_KEY=gsk_OK\n")
        with mock.patch.dict(os.environ, {"AI_GROQ_API_KEY": "gsk_OK"}, clear=False):
            env_diagnostics._raw_file_values.cache_clear()
            with override_settings(AI_PROVIDERS="groq", AI_GROQ_API_KEY="gsk_OK"):
                self.assertEqual(ai_provider_credentials(None), [])
