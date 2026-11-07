"""爆款贴图拆解：参考图暂存、异步任务、模型链路预算。"""
import base64
import io
import json
import unittest
from unittest.mock import patch

from tests import support  # noqa: F401 - 在导入 app 前隔离账号库
from server import accounts, creator_tools, remix_reference, viral_remix_jobs, viral_remix_tasks


PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_1PX).decode()


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.ttls = {}

    def setex(self, key, ttl, value):
        self.store[key] = value
        self.ttls[key] = ttl

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)

    def close(self):
        return None


class ReferenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.redis = FakeRedis()
        patcher = patch.object(remix_reference, "_client", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_roundtrip_normalizes_and_drops(self):
        token = remix_reference.save([PNG_DATA_URL])
        self.assertRegex(token, remix_reference.TOKEN_PATTERN)
        images = remix_reference.load(token)
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0].startswith("data:image/jpeg;base64,"))
        self.assertEqual(self.redis.ttls[remix_reference.KEY_PREFIX + token],
                         remix_reference.TTL_SECONDS)
        remix_reference.drop(token)
        with self.assertRaisesRegex(ValueError, "已过期"):
            remix_reference.load(token)

    def test_expired_or_forged_token_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "凭证无效"):
            remix_reference.load("not-a-token")
        with self.assertRaisesRegex(ValueError, "已过期"):
            remix_reference.load("a" * 32)

    def test_rejects_non_image_payload_and_oversized_batches(self):
        with self.assertRaisesRegex(ValueError, "格式错误"):
            remix_reference.normalize("data:text/plain;base64,QQ==")
        with self.assertRaisesRegex(ValueError, "1到8张"):
            remix_reference.save([])
        with self.assertRaisesRegex(ValueError, "1到8张"):
            remix_reference.save([PNG_DATA_URL] * 9)

    def test_large_image_is_downscaled_to_1600(self):
        from PIL import Image
        big = Image.new("RGB", (2400, 1200), "white")
        buffer = io.BytesIO()
        big.save(buffer, format="PNG")
        normalized = remix_reference.normalize(
            "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode())
        with Image.open(io.BytesIO(base64.b64decode(normalized.split(",", 1)[1]))) as image:
            self.assertEqual(max(image.size), 1600)
            self.assertEqual(image.size, (1600, 800))


class AnalyzeJobTests(unittest.TestCase):
    def setUp(self):
        # provider_overrides() 会读 provider_settings，任务失败分支会写 jobs。
        accounts.init_db()

    def _job(self, **overrides):
        job = {"id": "job-1", "user_id": "user-1", "type": viral_remix_jobs.ANALYZE_TASK_TYPE,
               "lane": viral_remix_jobs.ANALYZE_LANE, "usage_id": "usage-1",
               "payload_json": json.dumps({"session_id": "session-1", "token": "a" * 32,
                                           "goal": "换角度", "preserve_person": False})}
        job.update(overrides)
        return job

    def test_submit_analyze_reserves_points_and_keeps_images_out_of_the_payload(self):
        captured = {}

        def create_job(user_id, kind, lane, key, usage_id, payload):
            captured.update(kind=kind, lane=lane, key=key, payload=payload)
            return {"id": "job-1", "usage_id": usage_id}

        with patch.object(accounts, "pricing_rule", return_value={"points": 2}) as rule, \
             patch.object(accounts, "reserve_points", return_value="usage-1") as reserve, \
             patch.object(accounts, "create_job", side_effect=create_job):
            job = viral_remix_jobs.submit_analyze("user-1", "session-1", "a" * 32, "换角度")
        self.assertEqual(job["id"], "job-1")
        rule.assert_called_once_with("POST", "/api/viral-remix/analyze")
        self.assertEqual(reserve.call_args.args[1], {"points": 2})
        self.assertEqual(captured["kind"], "viral_remix.analyze")
        self.assertEqual(captured["lane"], "text")
        self.assertEqual(set(captured["payload"]),
                         {"session_id", "token", "goal", "preserve_person"})
        self.assertNotIn("images", captured["payload"])

    def test_analyze_task_writes_result_settles_and_drops_reference(self):
        job = self._job()
        analysis = {"ideas": [{"id": "A"}], "visual_contract": {"asset_type": "poster"}}
        with patch.object(accounts, "claim_job", return_value=job), \
             patch.object(remix_reference, "load", return_value=["data:image/jpeg;base64,AAA"]) as load, \
             patch.object(remix_reference, "drop") as drop, \
             patch.object(creator_tools, "viral_remix_analysis", return_value=dict(analysis)), \
             patch("server.remix_contract.build", return_value={"category": "poster", "fingerprint": "fp"}), \
             patch.object(accounts, "save_workbench_session") as save, \
             patch.object(accounts, "finish_job") as finish, \
             patch.object(viral_remix_jobs, "settle_analyze") as settle:
            result = viral_remix_tasks.analyze_job.run("job-1")
        self.assertEqual(result["status"], "succeeded")
        load.assert_called_once_with("a" * 32)
        drop.assert_called_once_with("a" * 32)
        stored = finish.call_args.args[1]["result"]
        self.assertEqual(stored["content_type"], "poster")
        self.assertEqual(stored["source_fingerprint"], "fp")
        save.assert_called_once()
        self.assertEqual(save.call_args.args[0], "user-1")
        self.assertEqual(save.call_args.args[1]["id"], "session-1")
        # 只有归一化后的首图会跟着 session 走，任务负载里没有图片。
        self.assertEqual(save.call_args.args[1]["person_reference"], None)
        settle.assert_called_once()
        self.assertTrue(settle.call_args.args[1])

    def test_analyze_task_refunds_when_the_reference_expired(self):
        job = self._job()
        with patch.object(accounts, "claim_job", return_value=job), \
             patch.object(remix_reference, "load", side_effect=ValueError("参考图已过期，请重新上传后再拆解")), \
             patch.object(remix_reference, "drop") as drop, \
             patch.object(accounts, "fail_job") as fail, \
             patch.object(viral_remix_jobs, "settle_analyze") as settle:
            result = viral_remix_tasks.analyze_job.run("job-1")
        self.assertEqual(result["status"], "failed")
        self.assertIn("已过期", fail.call_args.args[1])
        self.assertFalse(settle.call_args.args[1])
        drop.assert_called_once_with("a" * 32)

    def test_analyze_task_ignores_jobs_claimed_by_another_worker(self):
        with patch.object(accounts, "claim_job", return_value=None), \
             patch.object(creator_tools, "viral_remix_analysis") as analysis:
            result = viral_remix_tasks.analyze_job.run("job-1")
        self.assertEqual(result["status"], "ignored")
        analysis.assert_not_called()

    def test_public_analyze_exposes_result_only_when_succeeded(self):
        job = self._job(status="running", result_json=json.dumps({"result": {"ideas": []}}))
        public = viral_remix_jobs.public_analyze(job)
        self.assertIsNone(public["result"])
        self.assertIn("拆解", public["stage"])
        job["status"] = "succeeded"
        self.assertEqual(viral_remix_jobs.public_analyze(job)["result"], {"ideas": []})


class VisionModelChainTests(unittest.TestCase):
    def test_primary_model_and_budget_come_from_the_environment(self):
        import requests
        seen = {}

        def post(url, headers=None, json=None, timeout=None, verify=None):
            seen['model'] = json['model']
            seen['timeout'] = timeout
            raise requests.ReadTimeout('slow')

        with patch.dict("os.environ", {"WECHAT_REMIX_PRIMARY_MODEL": "gpt-6.1-sol",
                                       "WECHAT_REMIX_FALLBACK_MODEL": "",
                                       "WECHAT_REMIX_ATTEMPT_SECONDS": "100"}, clear=False), \
             patch("server.creator_tools.requests.post", side_effect=post):
            with self.assertRaises(creator_tools.workbench.ProviderError):
                creator_tools._remix_vision({"model": "gpt-6.1-terra"})
        self.assertEqual(seen['model'], "gpt-6.1-sol")
        self.assertEqual(seen['timeout'], (10, 100))

    def test_default_chain_keeps_the_two_attempt_budgets(self):
        import requests
        budgets = []

        def post(url, headers=None, json=None, timeout=None, verify=None):
            budgets.append((json['model'], timeout[1]))
            raise requests.ReadTimeout('slow')

        with patch.dict("os.environ", {"WECHAT_REMIX_PRIMARY_MODEL": "",
                                       "WECHAT_REMIX_FALLBACK_MODEL": "gpt-6.1-sol",
                                       "WECHAT_REMIX_ATTEMPT_SECONDS": "65,80"}, clear=False), \
             patch("server.creator_tools.requests.post", side_effect=post):
            with self.assertRaises(creator_tools.workbench.ProviderError):
                creator_tools._remix_vision({"model": "gpt-6.1-terra"})
        self.assertEqual(budgets, [("gpt-6.1-terra", 65), ("gpt-6.1-sol", 80)])


if __name__ == "__main__":
    unittest.main()


class RemixAnalysisApiTests(unittest.TestCase):
    """路由层：参考图 → 入队 → 轮询，全程不传图片本身。"""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from server.main import app
        cls.client = TestClient(app)
        login = cls.client.post("/api/auth/login", json={
            "email": "admin@example.com", "password": "testing-pass-123"})
        assert login.status_code == 200, login.text
        cls.user_id = login.json()["user"]["id"]
        recharge = cls.client.post("/api/admin/recharge", json={
            "user_id": cls.user_id, "points": 200, "bucket": "trial", "note": "拆解队列测试积分"})
        assert recharge.status_code == 200, recharge.text

    def test_reference_then_submit_then_poll(self):
        with patch.object(remix_reference, "save", return_value="a" * 32), \
             patch.object(remix_reference, "load", return_value=["data:image/jpeg;base64,AAA"]), \
             patch.object(viral_remix_tasks, "analyze_dispatch", return_value="celery-1") as dispatch:
            reference = self.client.post("/api/viral-remix/reference", json={"images": [PNG_DATA_URL]})
            self.assertEqual(reference.status_code, 200, reference.text)
            token = reference.json()["token"]
            self.assertEqual(token, "a" * 32)

            queued = self.client.post("/api/viral-remix/analysis", json={
                "token": token, "sessionId": "sessionabcdefgh", "goal": "换角度"})
            self.assertEqual(queued.status_code, 202, queued.text)
            job = queued.json()["job"]
            self.assertEqual(job["status"], "queued")
            dispatch.assert_called_once_with(job["id"])

            # 任务负载里只有 token，没有参考图本身。
            row = accounts.job(job["id"])
            payload = json.loads(row["payload_json"])
            self.assertEqual(payload["token"], token)
            self.assertNotIn("images", payload)
            self.assertNotIn("imageData", payload)

            polled = self.client.get(f"/api/viral-remix/analysis/{job['id']}")
            self.assertEqual(polled.status_code, 200, polled.text)
            self.assertEqual(polled.json()["job"]["id"], job["id"])

    def test_expired_reference_fails_before_charging(self):
        balance_before = accounts.wallet_summary(self.user_id)["balance"]
        with patch.object(remix_reference, "load",
                          side_effect=ValueError("参考图已过期，请重新上传后再拆解")):
            response = self.client.post("/api/viral-remix/analysis", json={"token": "b" * 32})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIn("已过期", response.json()["detail"])
        balance_after = accounts.wallet_summary(self.user_id)["balance"]
        self.assertEqual(balance_before, balance_after)

    def test_reference_endpoint_reports_bad_images(self):
        with patch.object(remix_reference, "save", side_effect=ValueError("参考图格式错误，请上传 PNG、JPG 或 WebP")):
            response = self.client.post("/api/viral-remix/reference", json={"images": ["bad"]})
        self.assertEqual(response.status_code, 422, response.text)

    def test_unknown_or_foreign_job_is_not_found(self):
        response = self.client.get("/api/viral-remix/analysis/" + "f" * 20)
        self.assertEqual(response.status_code, 404, response.text)


class RemixQueueFrontendContractTests(unittest.TestCase):
    def test_app_js_submits_and_polls_without_a_285_second_request(self):
        from pathlib import Path
        script = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("/api/viral-remix/reference", script)
        self.assertIn("/api/viral-remix/analysis", script)
        self.assertIn("pollRemixAnalysisJob", script)
        self.assertIn("shrinkRemixImage", script)
        self.assertIn("REMIX_MAX_EDGE = 1600", script)
        self.assertNotIn("AbortSignal.timeout(285000)", script)
