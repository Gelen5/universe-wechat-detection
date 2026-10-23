"""AI 超市：快照归一化、过滤排序、精选与手工收录。"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import market, market_sync


RAW = [
    {"id": "a", "display_name": "PDF Tools", "description": "Extract text from PDF.",
     "authors": ["anthropics"], "is_official": True, "tags": ["pdf"],
     "category": "productivity", "source": {"repo": "anthropics/skills", "path": "/skills/pdf"},
     "metadata": {"stars": 40000}, "added_at": "2026-06-05"},
    {"id": "b", "display_name": "Taste Skill", "description": "Anti-slop frontend skill.",
     "authors": ["Leonxlnx"], "is_official": False, "tags": ["frontend"],
     "category": "design", "source": {"repo": "Leonxlnx/taste-skill", "path": "/taste-skill"},
     "metadata": {"stars": 38000}, "added_at": "2026-06-01"},
    {"id": "c", "display_name": "Three.js", "description": "3D scenes.",
     "authors": ["CloudAI-X"], "is_official": True, "tags": ["threejs"],
     "category": "design", "source": {"repo": "CloudAI-X/threejs-skills", "path": ""},
     "metadata": {"stars": 12000}, "added_at": "2026-07-18"},
    # 重复：同 repo+path，星标更低 → 应被丢弃
    {"id": "a-dup", "display_name": "PDF Tools (old)", "description": "dup",
     "category": "productivity", "source": {"repo": "anthropics/skills", "path": "/skills/pdf"},
     "metadata": {"stars": 10}, "added_at": "2026-01-01"},
]


class MarketNormalizeTests(unittest.TestCase):
    def test_dedupes_repo_path_and_keeps_higher_stars(self):
        items = market_sync.normalize(RAW)
        self.assertEqual(3, len(items))
        self.assertEqual("PDF Tools", items[0]["name"])
        self.assertEqual("design", items[1]["category"])
        self.assertEqual("设计", items[1]["category_zh"])

    def test_builds_github_tree_url(self):
        items = market_sync.normalize(RAW)
        pdf = next(item for item in items if item["id"] == "a")
        self.assertEqual("https://github.com/anthropics/skills/tree/HEAD/skills/pdf", pdf["url"])
        three = next(item for item in items if item["id"] == "c")
        self.assertEqual("https://github.com/CloudAI-X/threejs-skills", three["url"])

    def test_scan_counts_categories(self):
        counts = market_sync._category_counts(market_sync.normalize(RAW))
        self.assertEqual(1, counts["productivity"])
        self.assertEqual(2, counts["design"])


class MarketApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.env = patch.dict("os.environ", {"MARKET_DIR": str(self.dir), "MARKET_TRANSLATE": "0"})
        self.env.start()
        self.minimum = patch.object(market_sync, "MIN_ITEMS", 1)
        self.minimum.start()
        with patch.object(market_sync, "fetch_payload", return_value=(RAW, "test://source")):
            market_sync.sync(translate_items=False)
        app = FastAPI()
        app.include_router(market.router)
        self.client = TestClient(app)

    def tearDown(self):
        self.minimum.stop()
        self.env.stop()
        self.temp.cleanup()

    def write_custom(self, payload):
        market_sync.write_json(market_sync.custom_path(), payload)
        market._cache["custom_mtime"] = -1.0

    def test_lists_sorted_by_stars(self):
        data = self.client.get("/api/market/skills").json()
        self.assertEqual(3, data["total"])
        self.assertEqual(["a", "b", "c"], [row["id"] for row in data["items"]])

    def test_filters_by_category_and_query(self):
        design = self.client.get("/api/market/skills?category=design").json()
        self.assertEqual({"b", "c"}, {row["id"] for row in design["items"]})
        search = self.client.get("/api/market/skills?q=pdf").json()
        self.assertEqual(["a"], [row["id"] for row in search["items"]])

    def test_sorts_by_added_date(self):
        data = self.client.get("/api/market/skills?sort=added").json()
        self.assertEqual("c", data["items"][0]["id"])

    def test_pagination(self):
        data = self.client.get("/api/market/skills?page=2&page_size=2").json()
        self.assertEqual(3, data["total"])
        self.assertEqual(1, len(data["items"]))
        self.assertEqual(2, data["pages"])

    def test_meta_reports_counts(self):
        data = self.client.get("/api/market/meta").json()
        self.assertEqual(3, data["count"])
        self.assertEqual(3, data["repos"])
        self.assertEqual(2, data["official"])
        self.assertEqual({"design", "productivity"}, {row["slug"] for row in data["categories"]})

    def test_pins_and_hidden_apply(self):
        self.write_custom({"pins": [{"id": "c", "rank": 1, "note": "优先"}], "hidden": ["b"]})
        data = self.client.get("/api/market/skills").json()
        self.assertEqual({"a", "c"}, {row["id"] for row in data["items"]})
        featured = self.client.get("/api/market/skills?featured=true").json()
        self.assertEqual(["c"], [row["id"] for row in featured["items"]])
        manual_sort = self.client.get("/api/market/skills?sort=manual").json()
        self.assertEqual("c", manual_sort["items"][0]["id"])

    def test_manual_items_merge_and_override(self):
        self.write_custom({"items": [{
            "id": "mine", "name": "我的选题库", "description": "内部方法",
            "category": "productivity", "category_zh": "效率",
            "repo": "Gelen5/weChat-autoCreate", "path": "/skills/topic",
            "url": "https://github.com/Gelen5/weChat-autoCreate/tree/HEAD/skills/topic",
            "stars": 0, "added_at": "2026-10-24", "manual": True,
        }]})
        data = self.client.get("/api/market/skills?sort=manual").json()
        self.assertEqual(4, data["total"])
        self.assertTrue(any(row["id"] == "mine" and row["manual"] for row in data["items"]))

    def test_admin_can_pin_and_hide(self):
        with patch.object(market.accounts, "require_admin", return_value={"id": "u"}):
            response = self.client.post("/api/admin/market/pins",
                                        json={"pins": [{"id": "a", "rank": 1, "note": ""}]})
            self.assertEqual(200, response.status_code)
            response = self.client.post("/api/admin/market/hidden", json={"hidden": ["c"]})
            self.assertEqual(200, response.status_code)
            custom = self.client.get("/api/admin/market/custom").json()
        self.assertEqual(["a"], [pin["id"] for pin in custom["pins"]])
        self.assertEqual(["c"], custom["hidden"])
        visible = self.client.get("/api/market/skills").json()
        self.assertNotIn("c", [row["id"] for row in visible["items"]])


if __name__ == "__main__":
    unittest.main()
