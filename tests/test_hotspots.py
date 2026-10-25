"""热点广场：归一化、无 Redis 降级、接口形状。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import hotspots


PAYLOAD = {
    "status": "success",
    "items": [
        {"title": "日剧Vivant抹黑中国", "url": "https://s.weibo.com/weibo?q=1", "extra": {"info": "热搜第 1"}},
        {"title": "缺链接的条目", "url": "", "extra": {}},
        {"title": "http 条目", "url": "http://example.com/a", "extra": {}},
    ],
}


class NormalizeTests(unittest.TestCase):
    def test_keeps_only_https_and_fills_platform_name(self):
        items = hotspots._normalize("weibo", PAYLOAD)
        self.assertEqual(1, len(items))
        self.assertEqual("微博", items[0]["platform_zh"])
        self.assertEqual("热搜第 1", items[0]["hot"])
        self.assertEqual(1, items[0]["rank"])


class CollectTests(unittest.TestCase):
    def test_sync_reports_per_platform_counts(self):
        def fake_fetch(spec):
            platform, _ = spec
            return {"platform": platform, "ok": True, "items": hotspots._normalize(platform, PAYLOAD),
                    "seconds": 0.1, "error": ""}

        with patch.object(hotspots, "_redis", return_value=None), \
                patch.object(hotspots, "fetch_platform", side_effect=fake_fetch), \
                patch.object(hotspots, "_maybe_snapshot", return_value=0):
            result = hotspots.sync()
        self.assertEqual("ok", result["status"])
        self.assertEqual(len(hotspots.DEFAULT_PLATFORMS), len(result["platforms"]))
        self.assertEqual(len(hotspots.DEFAULT_PLATFORMS), result["items"])


class ApiTests(unittest.TestCase):
    def setUp(self):
        hotspots._LAST_ATTEMPT = 0.0  # 关掉懒加载节流，便于逐条验证
        app = FastAPI()
        app.include_router(hotspots.router)
        self.client = TestClient(app)

    def test_without_redis_it_falls_back_to_a_live_fetch(self):
        def fake_collect(platforms=None):
            rows = [{"platform": pid, "platform_zh": hotspots.NAMES[pid], "title": f"{pid} 热点",
                     "url": "https://example.com/x", "hot": "", "rank": 1, "excerpt": ""}
                    for pid in (platforms or hotspots.DEFAULT_PLATFORMS)]
            return [{"platform": row["platform"], "ok": True, "items": [row], "seconds": 0.1, "error": ""}
                    for row in rows]

        with patch.object(hotspots, "_redis", return_value=None), \
                patch.object(hotspots, "_collect", side_effect=fake_collect):
            data = self.client.get("/api/hotspots?limit=10").json()
        self.assertEqual(len(hotspots.DEFAULT_PLATFORMS), len(data["items"]))
        self.assertFalse(data["degraded"])
        self.assertTrue(all(item["url"].startswith("https://") for item in data["items"]))

    def test_platform_filter_and_search(self):
        def fake_collect(platforms=None):
            row = {"platform": "weibo", "platform_zh": "微博", "title": "AI 大模型 讨论",
                   "url": "https://example.com/a", "hot": "", "rank": 1, "excerpt": ""}
            return [{"platform": "weibo", "ok": True, "items": [row], "seconds": 0.1, "error": ""}]

        with patch.object(hotspots, "_redis", return_value=None), \
                patch.object(hotspots, "_collect", side_effect=fake_collect):
            hit = self.client.get("/api/hotspots?q=大模型").json()
            miss = self.client.get("/api/hotspots?q=不存在").json()
        self.assertEqual(1, len(hit["items"]))
        self.assertEqual(0, len(miss["items"]))


if __name__ == "__main__":
    unittest.main()
