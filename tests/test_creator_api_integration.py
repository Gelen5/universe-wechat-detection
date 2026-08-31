import unittest
import os
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests import support  # noqa: F401 - configures isolated account database before app import
from server import creator_tools, workbench
from server.main import app


SHARED = {
    "textApiKey": "sk-test-shared-text",
    "imageApiKey": "sk-test-shared-image",
    "textBaseUrl": "https://text.example/v1",
    "imageBaseUrl": "https://image.example/v1",
    "textModel": "text-model",
    "imageModel": "image-model",
}

SERVER = {
    "text_key": "sk-server-text",
    "image_key": "sk-server-image",
    "text_base": "https://server-text.example/v1",
    "image_base": "https://server-image.example/v1",
    "text_model": "server-text-model",
    "image_model": "server-image-model",
}


def current_settings():
    return {
        "text_key": workbench._setting("WECHAT_TEXT_API_KEY"),
        "image_key": workbench._setting("WECHAT_IMAGE_API_KEY"),
        "text_base": workbench._setting("WECHAT_TEXT_API_BASE_URL"),
        "image_base": workbench._setting("WECHAT_IMAGE_API_BASE_URL"),
        "text_model": workbench._setting("WECHAT_TEXT_MODEL"),
        "image_model": workbench._setting("WECHAT_IMAGE_MODEL"),
    }


class CreatorApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.update({
            "WECHAT_TEXT_API_KEY": SERVER["text_key"],
            "WECHAT_IMAGE_API_KEY": SERVER["image_key"],
            "WECHAT_TEXT_API_BASE_URL": SERVER["text_base"],
            "WECHAT_IMAGE_API_BASE_URL": SERVER["image_base"],
            "WECHAT_TEXT_MODEL": SERVER["text_model"],
            "WECHAT_IMAGE_MODEL": SERVER["image_model"],
        })
        cls.client = TestClient(app)
        response = cls.client.post("/api/auth/login", json={
            "email": "admin@example.com",
            "password": "testing-pass-123",
        })
        assert response.status_code == 200, response.text
        user_id = response.json()["user"]["id"]
        response = cls.client.post("/api/admin/recharge", json={
            "user_id": user_id,
            "points": 1000,
            "bucket": "trial",
            "note": "接口测试积分",
        })
        assert response.status_code == 200, response.text

    def assert_shared_settings(self, captured):
        self.assertEqual(captured, SERVER)

    def test_shared_settings_reach_xiaohongshu_route(self):
        captured = {}

        def fake_package(*_args):
            captured.update(current_settings())
            return {
                "session_id": "xhs-session",
                "selected_title": "一个具体标题",
                "body": "第一步，先完成具体动作。" * 30,
                "cards": [{"index": index} for index in range(1, 7)],
            }

        with patch.object(creator_tools, "xiaohongshu_package", side_effect=fake_package):
            response = self.client.post("/api/xiaohongshu/package", json={
                **SHARED,
                "topic": "把创作流程做成可执行清单",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["package"]["cards"]), 6)
        self.assert_shared_settings(captured)

    def test_shared_settings_reach_tie_tu_route(self):
        captured = {}

        def fake_plan(*_args):
            captured.update(current_settings())
            return {"session_id": "tie-session", "cards": [{"index": 1}], "ratio": "3:4"}

        with patch.object(creator_tools, "tie_tu_plan", side_effect=fake_plan):
            response = self.client.post("/api/tie-tu/plan", json={
                **SHARED,
                "topic": "旅行换一种玩法",
                "imageCount": 1,
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["plan"]["ratio"], "3:4")
        self.assert_shared_settings(captured)

    def test_shared_image_settings_reach_card_generation_route(self):
        captured = {}

        def fake_image(*_args):
            captured.update(current_settings())
            return {"index": 1, "url": "/api/creator-tools/assets/tie-tu/session123/card-01.png"}

        with patch.object(creator_tools, "generate_card_image", side_effect=fake_image):
            response = self.client.post("/api/creator-tools/image", json={
                **SHARED,
                "tool": "tie-tu",
                "sessionId": "session123",
                "card": {"index": 1, "overlay_text": "慢一点也很好"},
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("card-01.png", response.json()["image"]["url"])
        self.assert_shared_settings(captured)

    def test_shared_text_settings_reach_hit_rewrite_route(self):
        captured = {}

        def fake_rewrite(title, body, _report):
            captured.update(current_settings())
            return {"title": title, "body": body, "change_summary": "只修复阻断项"}

        with patch.object(creator_tools, "rewrite_article", side_effect=fake_rewrite):
            response = self.client.post("/api/hit-detector/rewrite", json={
                **SHARED,
                "title": "退休以后先做这三件事",
                "body": "先记录真实开支，再和家人确认生活计划。",
                "detectorResult": {},
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["article"]["change_summary"], "只修复阻断项")
        self.assert_shared_settings(captured)

    def test_text_provider_test_uses_the_same_request_settings(self):
        captured = {}

        def fake_text(_prompt):
            captured.update(current_settings())
            return "连接成功"

        with patch.object(workbench, "_text", side_effect=fake_text):
            response = self.client.post("/api/providers/test", json={**SHARED, "kind": "text"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["message"], "连接成功")
        self.assert_shared_settings(captured)

    def test_frontend_has_account_wallet_and_six_tabs(self):
        root = Path(__file__).resolve().parent.parent
        script = (root / "static" / "app.js").read_text(encoding="utf-8")
        html = (root / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("const sharedApiPayload = () => ({})", script)
        self.assertIn('id="auth-modal"', html)
        self.assertIn('id="wallet-modal"', html)
        self.assertIn('id="api-settings-button" type="button" role="menuitem" hidden', html)
        self.assertIn('id="shared-text-api-key"', html)
        self.assertIn('id="shared-image-api-key"', html)
        self.assertIn("currentAccount?.email?.toLowerCase() === 'gelen5@163.com'", script)
        self.assertIn('id="admin-users-button"', html)
        self.assertIn('id="admin-users-modal"', html)
        self.assertIn('id="impersonation-banner"', html)
        self.assertIn("/api/admin/impersonate", script)
        self.assertIn("/api/auth/stop-impersonation", script)
        self.assertIn("[502, 503, 504].includes(response.status)", script)
        self.assertIn('id="download-workbench-html"', html)
        self.assertIn("html_download_url", script)
        self.assertNotIn("shared-use-real", html)
        self.assertEqual(html.count("data-view="), 6)


if __name__ == "__main__":
    unittest.main()
