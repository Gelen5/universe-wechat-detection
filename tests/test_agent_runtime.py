from __future__ import annotations

import unittest
from unittest.mock import patch

from tests import support  # noqa: F401
from server.agent import runtime
from server.providers import ProviderRequestError
from server.skills.registry import get_registry


class AgentRuntimeTests(unittest.TestCase):
    def test_every_manifest_tool_has_a_registered_executor(self):
        registry = get_registry(refresh=True)
        for manifest in registry.list():
            resolved = runtime.resolve_tools(manifest.id, registry=registry)
            self.assertEqual({tool.name for tool in manifest.tools}, set(resolved), manifest.id)

    def test_model_service_uses_server_side_shared_provider_settings(self):
        settings = {
            "text_api_key": "text-secret", "image_api_key": "image-secret",
            "text_base_url": "https://text.example/v1", "image_base_url": "https://image.example/v1",
            "text_model": "text-model", "image_model": "image-model",
        }
        with patch("server.agent.runtime.accounts.provider_settings", return_value=settings):
            service = runtime.build_model_service()
        self.assertEqual("text-model", service.text_provider.text_model)
        self.assertEqual("image-model", service.image_provider.image_model)

    def test_missing_text_provider_fails_before_network_access(self):
        with patch("server.agent.runtime.accounts.provider_settings", return_value={}):
            with patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(ProviderRequestError, "尚未配置"):
                    runtime.build_model_service()


if __name__ == "__main__":
    unittest.main()
