"""选题的「真搜索」：多查询、去重、抓正文摘要。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from server import workbench_research as research

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>t</title>
<item><title>{title}</title><link>https://example.com/{slug}</link>
<description>摘要</description><pubDate>Thu, 22 Oct 2026 10:00:00 GMT</pubDate></item>
</channel></rss>"""


class FakeResponse:
    def __init__(self, body: bytes):
        self.content = body

    def raise_for_status(self):
        return None


class TopicQueryTests(unittest.TestCase):
    def test_queries_are_targeted_and_bounded(self):
        queries = research.topic_queries("AI 工具实测", limit=3)
        self.assertEqual(3, len(queries))
        self.assertTrue(all("AI 工具实测" in query for query in queries))
        self.assertEqual(len(set(queries)), len(queries))

    def test_empty_topic_yields_nothing(self):
        self.assertEqual([], research.topic_queries("   "))


class SearchFanOutTests(unittest.TestCase):
    def fake_get(self, url, params=None, **kwargs):
        query = (params or {}).get("q", "q")
        slug = f"{abs(hash(query)) % 10000}"
        return FakeResponse(RSS.format(title=query, slug=slug).encode())

    def test_multiple_queries_are_executed_and_deduped(self):
        queries = research.topic_queries("AI 工具", limit=2)
        with patch.object(research.requests, "get", side_effect=self.fake_get):
            result = research.search("AI 工具", queries=queries)
        self.assertEqual(queries, result["queries"])
        # 两个查询 × 两个 provider，按 URL 去重后每个查询只剩一条
        self.assertEqual(2, len(result["sources"]))
        self.assertEqual("partial", result["status"])

    def test_fetched_pages_are_reported(self):
        def fake_fetch(source):
            item = dict(source)
            item["content"] = "正文" * 200
            return item

        with patch.object(research.requests, "get", side_effect=self.fake_get), \
                patch.object(research, "fetch_source", side_effect=fake_fetch):
            result = research.search("AI 工具", fetch=True, queries=["q1"], max_fetch=2)
        self.assertEqual(1, result["fetched_count"])
        self.assertEqual("complete", result["status"])
        self.assertTrue(result["fetched"][0]["content"])

    def test_total_failure_is_unavailable(self):
        with patch.object(research.requests, "get", side_effect=OSError("no network")):
            result = research.search("AI 工具")
        self.assertEqual("unavailable", result["status"])
        self.assertEqual([], result["sources"])

    def test_compact_limits_prompt_size(self):
        fetched = [{"url": "https://e.com/1", "title": "标题", "content": "正文" * 2000}]
        payload = research.compact({"status": "complete", "queries": ["q"],
                                    "sources": [{"url": "https://e.com/1", "title": "标题"}],
                                    "fetched": fetched})
        self.assertLessEqual(len(payload["fetched"][0]["excerpt"]), 700)
        self.assertEqual("q", payload["queries"][0])
        self.assertEqual("complete", payload["status"])


if __name__ == "__main__":
    unittest.main()
