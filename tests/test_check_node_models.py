"""Unit tests for the deployment-time node model probe."""
from __future__ import annotations

import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_node_models.py"
_spec = importlib.util.spec_from_file_location("check_node_models", _SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


class EffectiveModelsTests(unittest.TestCase):
    def test_node_override_and_text_fallback(self):
        stored = {"text_model": "gpt-6-astra"}
        env = {"WECHAT_TOPIC_MODEL": "fast-model"}
        with mock.patch.dict(os.environ, env, clear=False):
            for name in check.NODE_VARS:
                if name not in env and name != "WECHAT_TEXT_MODEL":
                    os.environ.pop(name, None)
            used = check.effective_models(stored)
        self.assertEqual(["draft", "intent", "layout", "outline", "review", "text"],
                         sorted(used["gpt-6-astra"]))
        self.assertEqual(["topic"], used["fast-model"])

    def test_database_text_model_outranks_environment(self):
        stored = {"text_model": "db-model"}
        with mock.patch.dict(os.environ, {"WECHAT_TEXT_MODEL": "env-model"}, clear=False):
            used = check.effective_models(stored)
        self.assertIn("db-model", used)
        self.assertNotIn("env-model", used)

    def test_default_is_used_when_nothing_is_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            used = check.effective_models({})
        self.assertEqual([check.DEFAULT_MODEL], list(used))

    def test_chat_root_strips_responses_suffix(self):
        self.assertEqual("https://relay/v1",
                         check._chat_root("https://relay/v1/responses"))
        self.assertEqual("https://relay/v1", check._chat_root("https://relay/v1/"))


class ProbeVerdictTests(unittest.TestCase):
    def test_success_is_ok(self):
        response = mock.Mock(status_code=200, text="{}")
        with mock.patch.object(check.requests, "post", return_value=response):
            ok, detail = check.probe("https://relay/v1/chat/completions", "k", "m")
        self.assertTrue(ok)
        self.assertEqual("ok", detail)

    def test_model_not_found_is_reported_with_body(self):
        response = mock.Mock(status_code=404,
                            text='{"error":{"code":"model_not_found"}}')
        with mock.patch.object(check.requests, "post", return_value=response):
            ok, detail = check.probe("https://relay/v1/chat/completions", "k", "m")
        self.assertFalse(ok)
        self.assertIn("404", detail)
        self.assertIn("model_not_found", detail)

    def test_network_error_is_not_an_exception(self):
        with mock.patch.object(check.requests, "post", side_effect=TimeoutError("boom")):
            ok, detail = check.probe("https://relay/v1/chat/completions", "k", "m")
        self.assertFalse(ok)
        self.assertIn("TimeoutError", detail)


if __name__ == "__main__":
    unittest.main()
