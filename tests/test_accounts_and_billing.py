import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests import support  # noqa: F401 - configures isolated account database before app import
from server import creator_tools
from server.main import app


class AccountAndBillingTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        suffix = id(self)
        response = self.client.post("/api/auth/register", json={
            "email": f"user-{suffix}@example.com",
            "password": "testing-pass-123",
            "display_name": "积分用户",
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.user = response.json()["user"]
        self.assertEqual(self.user["role"], "user")

    def test_protected_api_requires_login(self):
        anonymous = TestClient(app)
        response = anonymous.get("/api/wallet")
        self.assertEqual(response.status_code, 401)

    def test_non_owner_cannot_recharge_points(self):
        response = self.client.post("/api/admin/recharge", json={
            "user_id": self.user["id"], "points": 100, "bucket": "trial", "note": "越权测试",
        })
        self.assertEqual(response.status_code, 403)

    def test_non_owner_cannot_read_or_change_provider_settings(self):
        self.assertEqual(self.client.get("/api/admin/provider-settings").status_code, 403)
        response = self.client.post("/api/admin/provider-settings", json={"text_api_key": "forbidden"})
        self.assertEqual(response.status_code, 403)

    def test_admin_can_save_settings_without_reading_secrets_back(self):
        admin = TestClient(app)
        admin.post("/api/auth/login", json={"email": "admin@example.com", "password": "testing-pass-123"})
        response = admin.post("/api/admin/provider-settings", json={
            "text_api_key": "sk-server-text", "text_model": "server-text-model",
        })
        self.assertEqual(response.status_code, 200, response.text)
        settings = response.json()["settings"]
        self.assertTrue(settings["text_configured"])
        self.assertEqual(settings["text_model"], "server-text-model")
        self.assertNotIn("text_api_key", settings)
        self.assertNotIn("sk-server-text", response.text)

    def test_admin_can_recharge_and_successful_request_consumes_points(self):
        admin = TestClient(app)
        login = admin.post("/api/auth/login", json={
            "email": "admin@example.com",
            "password": "testing-pass-123",
        })
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(login.json()["user"]["role"], "admin")
        recharge = admin.post("/api/admin/recharge", json={
            "user_id": self.user["id"], "points": 100, "bucket": "trial", "note": "新用户测试",
        })
        self.assertEqual(recharge.status_code, 200, recharge.text)

        with patch.object(creator_tools, "detect_article", return_value={"scores": {"total": 80}}):
            response = self.client.post("/api/hit-detector/analyze", json={
                "title": "一个真实标题", "body": "这是一段用于测试的完整正文。",
            })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers.get("X-Points-Charged"), "5")
        wallet = self.client.get("/api/wallet").json()["wallet"]
        self.assertEqual(wallet["balance"], 95)

    def test_admin_can_view_user_stats_and_safely_switch_user(self):
        admin = TestClient(app)
        login = admin.post("/api/auth/login", json={"email": "admin@example.com", "password": "testing-pass-123"})
        self.assertEqual(login.status_code, 200)
        overview = admin.get("/api/admin/overview")
        self.assertEqual(overview.status_code, 200)
        self.assertGreaterEqual(overview.json()["overview"]["users"], 2)
        detail = admin.get(f"/api/admin/users/{self.user['id']}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(detail.json()["user"]["email"], self.user["email"])

        switched = admin.post("/api/admin/impersonate", json={"user_id": self.user["id"]})
        self.assertEqual(switched.status_code, 200, switched.text)
        self.assertTrue(switched.json()["user"]["impersonation"]["active"])
        self.assertEqual(admin.get("/api/auth/me").json()["user"]["id"], self.user["id"])
        self.assertEqual(admin.get("/api/admin/overview").status_code, 403)

        restored = admin.post("/api/auth/stop-impersonation")
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["user"]["role"], "admin")
        self.assertEqual(admin.get("/api/admin/overview").status_code, 200)

    def test_failed_request_refunds_reserved_points(self):
        admin = TestClient(app)
        admin.post("/api/auth/login", json={"email": "admin@example.com", "password": "testing-pass-123"})
        admin.post("/api/admin/recharge", json={
            "user_id": self.user["id"], "points": 20, "bucket": "trial", "note": "退款测试",
        })
        with patch.object(creator_tools, "detect_article", side_effect=RuntimeError("模拟失败")):
            response = self.client.post("/api/hit-detector/analyze", json={
                "title": "一个真实标题", "body": "这是一段用于测试的完整正文。",
            })
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.headers.get("X-Points-Refunded"), "5")
        wallet = self.client.get("/api/wallet").json()
        self.assertEqual(wallet["wallet"]["balance"], 20)
        self.assertTrue(any(item["kind"] == "refund" for item in wallet["transactions"]))

    def test_insufficient_points_blocks_before_tool_execution(self):
        with patch.object(creator_tools, "detect_article") as detector:
            response = self.client.post("/api/hit-detector/analyze", json={
                "title": "一个真实标题", "body": "这是一段用于测试的完整正文。",
            })
        self.assertEqual(response.status_code, 402)
        detector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
