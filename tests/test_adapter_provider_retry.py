import unittest
from contextlib import nullcontext
from unittest.mock import patch

from server import workbench
from server.providers import ProviderRequestError
from server.skills.adapter_support import with_provider
from vendor.skills.wechat_writer.adapter import create_tools


class AdapterProviderRetryTests(unittest.TestCase):
    def test_search_topics_keeps_actual_source_evidence_separate_from_suggestions(self):
        def fake_suggestions(topic, persona, session):
            session["topic_research"] = {
                "checked_at": "2026-10-01T00:00:00Z", "status": "partial",
                "sources": [{"provider": "google-news", "title": "真实搜索标题",
                             "url": "https://example.org/news", "published_at": "2026-09-30"}],
            }
            session["skill_hotspots"] = [{"title": "榜单标题", "sources": ["weibo"]}]
            return [{"title": "模型拟题"}]

        with patch("vendor.skills.wechat_writer.adapter.with_provider", side_effect=lambda call: call()), patch(
            "vendor.skills.wechat_writer.adapter.workbench._suggestions", side_effect=fake_suggestions
        ):
            result = create_tools()["search_topics"]({"topic": "情感"}, None)
        self.assertEqual(result.data["topics"][0]["title"], "模型拟题")
        self.assertEqual(result.data["evidence"]["search_sources"][0]["url"], "https://example.org/news")
        self.assertIn("摘要未核实原文", result.artifacts[0].content)
        self.assertIn("采集时间不是内容发布日期", result.artifacts[0].content)

    def test_transient_error_retries_only_failing_tool(self):
        calls = 0

        def invoke():
            nonlocal calls
            calls += 1
            if calls < 3:
                try:
                    raise ProviderRequestError("connection reset", transient=True)
                except ProviderRequestError as exc:
                    raise workbench.ProviderError("text API failed") from exc
            return "ok"

        with patch("server.skills.adapter_support.time.sleep"), patch(
            "server.skills.adapter_support.workbench.provider_overrides", return_value=nullcontext()
        ):
            self.assertEqual(with_provider(invoke), "ok")
        self.assertEqual(calls, 3)

    def test_nontransient_error_is_not_retried(self):
        calls = 0

        def invoke():
            nonlocal calls
            calls += 1
            raise workbench.ProviderError("invalid response")

        with patch("server.skills.adapter_support.workbench.provider_overrides", return_value=nullcontext()), self.assertRaises(workbench.ProviderError):
            with_provider(invoke)
        self.assertEqual(calls, 1)

    def test_typeset_session_contains_topic(self):
        def fake_typeset(session):
            self.assertEqual(session["topic"], "测试标题")
            return "<p>正文</p>"

        with patch("server.skills.adapter_support.workbench.provider_overrides", return_value=nullcontext()), patch(
            "vendor.skills.wechat_writer.adapter.workbench._typeset", side_effect=fake_typeset
        ):
            result = create_tools()["typeset_article"](
                {"title": "测试标题", "article": "正文"}, None)
        self.assertEqual(result.data["html"], "<p>正文</p>")


if __name__ == "__main__":
    unittest.main()
