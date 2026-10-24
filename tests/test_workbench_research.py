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
    def setUp(self):
        # 只验证「多查询扇出 + 去重」，把新增的搜狗/行业 RSS 源隔离掉
        empty = {'status': 'empty', 'entries': []}
        self._sogou = patch.object(research, '_run_sogou', return_value={'provider': 'sogou-weixin', 'query': '', **empty})
        self._feed = patch.object(research, '_run_feed', return_value={'provider': 'feed', 'query': '', **empty})
        self._sogou.start()
        self._feed.start()

    def tearDown(self):
        self._sogou.stop()
        self._feed.stop()

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

SOGOU_HTML = """<html><body>
<div class="news-list"><ul>
<li><h3><a href="/link?url=abc123" target="_blank">AI 大模型周报：Kimi 新版本</a></h3></li>
<li><h3><a href="/link?url=def456" target="_blank">大模型价格战继续</a></h3></li>
</ul></div></body></html>"""


class TextResponse:
    def __init__(self, body: str, status: int = 200):
        self.content = body.encode('utf-8')
        self.text = body
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise research.requests.HTTPError(f"status {self.status_code}")


class MultiSourceTests(unittest.TestCase):
    def test_sogou_parses_headlines(self):
        with patch.object(research.requests, 'get', return_value=TextResponse(SOGOU_HTML)):
            run = research._run_sogou(('AI 大模型', 10))
        self.assertEqual('ok', run['status'])
        self.assertEqual(2, len(run['entries']))
        self.assertTrue(run['entries'][0]['url'].startswith('https://weixin.sogou.com/link?url='))
        self.assertEqual('sogou-weixin', run['entries'][0]['provider'])

    def test_sogou_block_page_is_unavailable(self):
        with patch.object(research.requests, 'get', return_value=TextResponse('<html>请输入验证码</html>')):
            run = research._run_sogou(('AI', 10))
        self.assertEqual('unavailable', run['status'])
        self.assertEqual([], run['entries'])

    def test_feed_upgrades_http_links(self):
        rss = RSS.replace('https://example.com/', 'http://example.com/')
        with patch.object(research.requests, 'get', return_value=TextResponse(rss)):
            run = research._run_feed(('sina-tech', 'https://rss.example', 10))
        self.assertEqual('ok', run['status'])
        self.assertTrue(all(entry['url'].startswith('https://') for entry in run['entries']))

    def test_search_merges_feeds_with_search_results(self):
        feed_entry = {'title': 'AI 大模型 行业动态', 'url': 'https://feed.example/1',
                      'excerpt': '大模型 应用', 'published_at': '', 'provider': 'infoq-cn',
                      'query': '', 'verification': 'feed_headline_only'}
        search_entry = {'title': 'AI 大模型 热点', 'url': 'https://search.example/1',
                        'excerpt': '', 'published_at': '', 'provider': 'bing',
                        'query': 'AI 大模型 热点 讨论', 'verification': 'search_excerpt_only'}
        with patch.object(research, '_run_query', return_value={'provider': 'bing', 'query': 'q', 'status': 'ok', 'entries': [search_entry]}), \
                patch.object(research, '_run_sogou', return_value={'provider': 'sogou-weixin', 'query': 'q', 'status': 'empty', 'entries': []}), \
                patch.object(research, '_run_feed', return_value={'provider': 'infoq-cn', 'query': '', 'status': 'ok', 'entries': [feed_entry]}):
            result = research.search('AI 大模型', queries=['AI 大模型 热点 讨论'])
        providers = {source['provider'] for source in result['sources']}
        self.assertEqual({'bing', 'infoq-cn'}, providers)
        self.assertEqual(2, len(result['sources']))
        self.assertIn('infoq-cn', result['providers'])
