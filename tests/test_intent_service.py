"""路由服务必须用完整 URL，并且默认走更快的 chat 端点。"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from server.agent import runtime


class IntentServiceTests(unittest.TestCase):
    def build(self, env, stored):
        with patch.dict(os.environ, env, clear=False), \
                patch.object(runtime.accounts, "provider_settings", return_value=stored):
            os.environ.pop("WECHAT_INTENT_API_BASE_URL", None)
            return runtime.build_intent_service()

    def test_no_model_means_no_service(self):
        with patch.dict(os.environ, {"WECHAT_INTENT_MODEL": ""}, clear=False):
            self.assertIsNone(runtime.build_intent_service())

    def test_responses_base_is_rewritten_to_chat_with_scheme(self):
        service = self.build(
            {"WECHAT_INTENT_MODEL": "fast-model"},
            {"text_api_key": "k", "text_base_url": "https://relay.example/v1/responses"},
        )
        self.assertEqual("https://relay.example/v1", service.text_provider.base_url)
        self.assertFalse(service.text_provider.responses_api)
        self.assertEqual("fast-model", service.text_provider.text_model)

    def test_missing_settings_still_produce_a_usable_url(self):
        service = self.build({"WECHAT_INTENT_MODEL": "fast-model"}, {})
        self.assertTrue(service.text_provider.base_url.startswith("https://"))
        self.assertEqual("https://api.openai.com/v1", service.text_provider.base_url)


if __name__ == "__main__":
    unittest.main()
