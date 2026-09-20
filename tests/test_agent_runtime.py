from __future__ import annotations

import hashlib
import unittest
from unittest.mock import MagicMock, patch

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

    def test_wechat_image_tool_uses_model_service_with_run_attribution(self):
        service = MagicMock()
        service.generate_image.return_value = {"data": [{"url": "https://example.test/image.png"}]}
        tools = runtime.resolve_tools(
            "wechat_writer", registry=get_registry(), model_service=service,
            run_id="run-1", user_id="user-1",
        )
        result = tools["generate_image"].execute({
            "prompt": "清晨窗边", "size": "768x1024", "count": 2,
        })
        self.assertEqual("https://example.test/image.png", result["data"][0]["url"])
        request_hash = hashlib.sha256(
            f"{'清晨窗边'}\0{'768x1024'}\0{2}".encode("utf-8")
        ).hexdigest()[:24]
        service.generate_image.assert_called_once_with(
            "清晨窗边", size="768x1024", count=2,
            idempotency_key=f"run-1:generate_image:{request_hash}",
            run_id="run-1", user_id="user-1",
        )


if __name__ == "__main__":
    unittest.main()
