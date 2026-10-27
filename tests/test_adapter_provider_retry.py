import unittest
from contextlib import nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from server import workbench
from server.providers import ProviderRequestError
from server.skills.adapter_support import with_provider
from vendor.skills.wechat_writer.adapter import create_tools


class AdapterProviderRetryTests(unittest.TestCase):
    def test_write_article_keeps_authoritative_user_prohibitions(self):
        context = SimpleNamespace(conversation_id='c', user_id='u', run_id='r',
            input_artifacts=lambda: [], emit=lambda *_args: None)
        frame = {'name': '观点', 'outline': ['一', '二']}
        with patch('vendor.skills.wechat_writer.adapter.conversation_repository.get_run', return_value={'trigger_message_id': 'm'}), \
             patch('vendor.skills.wechat_writer.adapter.conversation_repository.get_message', return_value={'content': '不得编造对白和心理活动'}), \
             patch('vendor.skills.wechat_writer.adapter.with_provider', side_effect=lambda fn: fn()), \
             patch('vendor.skills.wechat_writer.adapter.workbench._draft', return_value='# 标题\n正文') as draft:
            create_tools()['write_article']({'title': '标题', 'requirements': '写观点', 'framework': frame}, context)
        self.assertIn('不得编造对白和心理活动', draft.call_args.args[3])

    def test_outline_uses_existing_skill_and_creates_editable_artifact(self):
        frame = {"name": "SCQA", "outline": ["场景", "冲突"], "research": {}}
        with patch("vendor.skills.wechat_writer.adapter.with_provider", side_effect=lambda call: call()), patch(
            "vendor.skills.wechat_writer.adapter.workbench._framework", return_value=frame) as skill:
            result = create_tools()["create_outline"]({"title": "测试选题"}, None)
        skill.assert_called_once()
        self.assertEqual("outline", result.artifacts[0].type)
        self.assertIn("1. 场景", result.artifacts[0].content)

    def test_search_topics_keeps_actual_source_evidence_separate_from_suggestions(self):
        def fake_suggestions(topic, persona, session, progress=None):
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

    def test_square_hotspot_evidence_preserves_url_rank_and_observation_time(self):
        def fake_suggestions(topic, persona, session, progress=None):
            session['square_hotspots'] = {'status': 'matched', 'items': [
                {'title': 'AI 工具', 'url': 'https://example.com/hot', 'platform': 'douyin',
                 'platform_zh': '抖音', 'rank': 3, 'observed_at': '2026-10-28T00:00:00+00:00'}]}
            return [{'title': '方向'}]
        with patch('vendor.skills.wechat_writer.adapter.with_provider', side_effect=lambda call: call()), \
             patch('vendor.skills.wechat_writer.adapter.workbench._suggestions', side_effect=fake_suggestions):
            result = create_tools()['search_topics']({'topic': 'AI'}, None)
        evidence = result.data['evidence']
        assert evidence['square_hotspot_status'] == 'matched'
        assert evidence['search_sources'][0]['published_at'] == ''
        assert evidence['search_sources'][0]['observed_at'] == '2026-10-28T00:00:00+00:00'
        assert evidence['platform_hotspots'][0]['rank'] == 3
        assert 'https://example.com/hot' in result.artifacts[0].content

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

        context = SimpleNamespace(conversation_id="conversation", user_id="user")
        with patch("vendor.skills.wechat_writer.adapter.conversation_repository.list_artifacts", return_value=[]), patch(
            "server.skills.adapter_support.workbench.provider_overrides", return_value=nullcontext()), patch(
            "vendor.skills.wechat_writer.adapter.workbench._typeset", side_effect=fake_typeset
        ):
            result = create_tools()["typeset_article"](
                {"title": "测试标题", "article": "正文"}, context)
        self.assertEqual(result.data["html"], "<p>正文</p>")

    def test_deep_review_requires_user_request_not_model_tool_arguments(self):
        context = SimpleNamespace(conversation_id='conv', user_id='user', run_id='run',
            input_artifacts=lambda: [{'type': 'article', 'content': '原稿', 'created_at': '1'}],
            is_cancelled=lambda: False, emit=lambda *_args: None)
        report = {'gate': 'passed', 'changed': False, 'summary': '复核完成'}
        with patch('vendor.skills.wechat_writer.adapter.conversation_repository.get_run', return_value={'trigger_message_id': 'm'}), \
             patch('vendor.skills.wechat_writer.adapter.conversation_repository.get_message', return_value={'content': '正常去 AI'}), \
             patch('vendor.skills.wechat_writer.adapter.workbench.provider_overrides', return_value=nullcontext()), \
             patch('vendor.skills.wechat_writer.adapter.workbench._review', return_value=('原稿', report)) as local, \
             patch('vendor.skills.wechat_writer.adapter.workbench._deep_structure_review') as deep:
            create_tools()['review_article']({'article': '原稿', 'review_mode': 'deep_structure'}, context)
        local.assert_called_once()
        deep.assert_not_called()

    def test_negated_deep_review_stays_local(self):
        context = SimpleNamespace(conversation_id='conv', user_id='user', run_id='run',
            input_artifacts=lambda: [{'type': 'article', 'content': '原稿', 'created_at': '1'}],
            is_cancelled=lambda: False, emit=lambda *_args: None)
        with patch('vendor.skills.wechat_writer.adapter.conversation_repository.get_run', return_value={'trigger_message_id': 'm'}), \
             patch('vendor.skills.wechat_writer.adapter.conversation_repository.get_message', return_value={'content': '不要深度重构，只做局部审校'}), \
             patch('vendor.skills.wechat_writer.adapter.workbench.provider_overrides', return_value=nullcontext()), \
             patch('vendor.skills.wechat_writer.adapter.workbench._review', return_value=('原稿', {'gate': 'passed'})) as local, \
             patch('vendor.skills.wechat_writer.adapter.workbench._deep_structure_review') as deep:
            create_tools()['review_article']({'article': '原稿'}, context)
        local.assert_called_once()
        deep.assert_not_called()

    def test_explicit_deep_review_and_pending_review_cannot_be_typeset(self):
        context = SimpleNamespace(conversation_id='conv', user_id='user', run_id='run',
            input_artifacts=lambda: [{'type': 'article', 'content': '原稿', 'created_at': '1'}],
            is_cancelled=lambda: False, emit=lambda *_args: None)
        report = {'gate': 'passed', 'changed': True, 'summary': '重构完成'}
        with patch('vendor.skills.wechat_writer.adapter.conversation_repository.get_run', return_value={'trigger_message_id': 'm'}), \
             patch('vendor.skills.wechat_writer.adapter.conversation_repository.get_message', return_value={'content': '请深度重构'}), \
             patch('vendor.skills.wechat_writer.adapter.workbench.provider_overrides', return_value=nullcontext()), \
             patch('vendor.skills.wechat_writer.adapter.workbench._deep_structure_review', return_value=('新稿', report)) as deep:
            result = create_tools()['review_article']({'article': '原稿'}, context)
        deep.assert_called_once()
        self.assertEqual(result.artifacts[0].content, '新稿')
        pending = SimpleNamespace(conversation_id='conv', user_id='user', run_id='typeset',
            input_artifacts=lambda: [
                {'type':'article', 'content':'原稿', 'run_id':'review', 'created_at':'1'},
                {'type':'report', 'run_id':'review', 'content_json':{'source':'structural_rewrite', 'gate':'needs_review'}, 'created_at':'2'}])
        with self.assertRaises(workbench.ProviderError):
            create_tools()['typeset_article']({'article': '原稿'}, pending)

    def test_typeset_uses_the_submitted_article_snapshot_and_records_source(self):
        from server.skill_runtime import digest
        old = {"type": "article", "id": "old", "version": 1, "content": "旧正文。",
               "run_id": "old-run", "created_at": "2026-01-01T00:00:00+00:00"}
        revised = {"type": "article", "id": "revised", "version": 2, "content": "复核后的正文。",
                   "run_id": "review-run", "created_at": "2026-01-02T00:00:00+00:00"}
        context = SimpleNamespace(conversation_id="conversation", user_id="user", run_id="run",
                                  input_artifacts=lambda: [old, revised])
        def fake_typeset(session):
            self.assertEqual(session['article'], revised['content'])
            return '<p>复核后的正文。</p>'
        with patch('vendor.skills.wechat_writer.adapter.with_provider', side_effect=lambda fn: fn()), \
             patch('vendor.skills.wechat_writer.adapter.workbench._typeset', side_effect=fake_typeset), \
             patch('vendor.skills.wechat_writer.adapter.conversation_repository.list_artifacts') as live:
            result = create_tools()['typeset_article']({'article': '模型误传旧稿'}, context)
        live.assert_not_called()
        meta = result.artifacts[0].content_json
        self.assertEqual(meta['source_article_id'], 'revised')
        self.assertEqual(meta['source_article_version'], 2)
        self.assertEqual(meta['source_article_sha256'], digest(revised['content']))

    def test_typeset_reuses_only_current_article_images(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "source.png"
            image.write_bytes(b"image bytes")
            artifacts = [
                {"type": "image", "storage_key": "old", "created_at": "2026-01-01T00:00:00+00:00"},
                {"type": "article", "run_id": "previous-run", "created_at": "2026-01-02T00:00:00+00:00"},
                {"type": "image", "storage_key": "new", "title": "清晨配图",
                 "created_at": "2026-01-03T00:00:00+00:00"},
                {"type": "article", "run_id": "current-run", "created_at": "2026-01-04T00:00:00+00:00"},
            ]
            context = SimpleNamespace(conversation_id="conversation", user_id="user", run_id="current-run",
                                      storage=SimpleNamespace(local_path=lambda key: image))

            def fake_typeset(session):
                self.assertEqual(len(session["images"]), 1)
                self.assertEqual(session["images"][0]["caption"], "清晨配图")
                self.assertEqual(session["images"][0]["kind"], "body")
                self.assertEqual((root / session["id"] / "images" / "image-1.png").read_bytes(), b"image bytes")
                return "<img>"

            with patch("vendor.skills.wechat_writer.adapter.conversation_repository.list_artifacts",
                       return_value=artifacts) as listed, patch(
                "vendor.skills.wechat_writer.adapter.workbench.OUTPUT_DIR", root), patch(
                "vendor.skills.wechat_writer.adapter.workbench._typeset", side_effect=fake_typeset), patch(
                "vendor.skills.wechat_writer.adapter.with_provider", side_effect=lambda call: call()):
                result = create_tools()["typeset_article"]({"article": "正文"}, context)
            listed.assert_called_once_with("conversation", "user")
            self.assertEqual(result.data["html"], "<img>")


if __name__ == "__main__":
    unittest.main()
