"""Regression tests for the workbench speed/correctness fixes.

Covers: the review node no longer fabricates reader verdicts, ``_text`` honours
the reasoning argument it advertises, and the outline node reuses the sources
the topic node already fetched.
"""
from __future__ import annotations

import unittest
from unittest import mock

from server import skill_article_adapter, workflow_engine, workbench


class _FakeProvider:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeResponse:
    text = "正文"


class _FakeService:
    last = None

    def __init__(self, provider, usage_recorder=None, cost_policy=None):
        self.provider = provider
        _FakeService.last = self

    def create_response(self, *args, **kwargs):
        return _FakeResponse()


class _FlakyService:
    """ModelService stub that fails on demand, so retry logic is observable."""

    last = None
    calls = 0
    script = None

    def __init__(self, provider, usage_recorder=None, cost_policy=None):
        self.provider = provider
        _FlakyService.last = self

    def create_response(self, *args, **kwargs):
        _FlakyService.calls += 1
        return _FlakyService.script(_FlakyService.calls)


class ReviewAdapterTests(unittest.TestCase):
    def test_revision_plan_is_built_from_real_review_rounds(self):
        review = {"rounds": [
            {"round": 0, "diagnosis": {"issues": [
                {"quote": "值得注意的是", "reason": "套话", "fix": "删掉"},
                {"quote": "核心原因只有一个", "reason": "绝对断言", "fix": "改为有条件"},
            ]}},
            {"round": 1, "diagnosis": {"issues": []}},
        ]}
        plan = skill_article_adapter._revision_plan_from(review)
        self.assertEqual(2, len(plan))
        self.assertEqual("web_review", plan[0]["source"])
        self.assertEqual(0, plan[0]["round"])
        self.assertEqual("值得注意的是", plan[0]["quote"])
        self.assertEqual("删掉", plan[0]["fix"])

    def test_revision_plan_is_empty_without_review(self):
        self.assertEqual([], skill_article_adapter._revision_plan_from(None))
        self.assertEqual([], skill_article_adapter._revision_plan_from({}))
        self.assertEqual([], skill_article_adapter._revision_plan_from({"rounds": [{}]}))


class ReasoningArgumentTests(unittest.TestCase):
    def _call(self, **kwargs):
        with mock.patch("server.providers.OpenAICompatibleProvider", _FakeProvider), \
             mock.patch("server.providers.ModelService", _FakeService), \
             mock.patch.dict("os.environ", {"WECHAT_TEXT_API_KEY": "test-key"}):
            return workbench._text("提示", **kwargs)

    def test_reasoning_argument_reaches_the_provider(self):
        self._call(reasoning="high")
        self.assertEqual("high", _FakeService.last.provider.kwargs["reasoning_effort"])

    def test_no_reasoning_argument_sends_no_effort(self):
        self._call()
        self.assertIsNone(_FakeService.last.provider.kwargs["reasoning_effort"])

    def test_review_override_wins(self):
        token = workbench.REVIEW_REASONING.set("low")
        try:
            self._call(reasoning="high")
        finally:
            workbench.REVIEW_REASONING.reset(token)
        self.assertEqual("low", _FakeService.last.provider.kwargs["reasoning_effort"])


class OutlineResearchReuseTests(unittest.TestCase):
    def _call(self, session, search):
        frame = {"name": "SCQA", "reason": "r", "outline": ["一", "二"]}
        with mock.patch.object(workbench, "_require_skill", lambda: None), \
             mock.patch.object(workbench.skill_runtime, "context",
                               lambda *a, **k: ("说明", {"name": "m"})), \
             mock.patch.object(workbench, "_json_text", lambda *a, **k: dict(frame)), \
             mock.patch.object(workbench, "_record_skill", lambda *a, **k: None), \
             mock.patch.object(workbench.workbench_research, "search", search):
            return workbench._framework("标题", "人格", "", session=session)

    def test_reuses_topic_research_instead_of_searching_again(self):
        cached = {"sources": [{"title": "已抓到的来源"}]}
        called = []
        result = self._call({"topic_research": cached},
                            lambda *a, **k: called.append(1) or {"sources": []})
        self.assertEqual([], called, "outline must not search again when the topic node already did")
        self.assertIs(cached, result["research"])

    def test_searches_when_no_cached_material(self):
        fresh = {"sources": [{"title": "新来源"}]}
        result = self._call({}, lambda *a, **k: fresh)
        self.assertIs(fresh, result["research"])

    def test_searches_when_cache_is_empty(self):
        fresh = {"sources": [{"title": "新来源"}]}
        result = self._call({"topic_research": {"sources": []}}, lambda *a, **k: fresh)
        self.assertIs(fresh, result["research"])

    def test_operator_can_force_a_fresh_search(self):
        fresh = {"sources": [{"title": "新来源"}]}
        with mock.patch.dict("os.environ", {"WECHAT_OUTLINE_RESEARCH": "fresh"}):
            result = self._call({"topic_research": {"sources": [{"title": "旧的"}]}},
                                lambda *a, **k: fresh)
        self.assertIs(fresh, result["research"])


class NodeModelTieringTests(unittest.TestCase):
    def _run(self, environ):
        captured = {}
        frame = {"name": "SCQA", "reason": "r", "outline": ["一", "二"]}

        def fake_json(*args, **kwargs):
            captured.update(kwargs)
            return dict(frame)

        with mock.patch.object(workbench, "_require_skill", lambda: None), \
             mock.patch.object(workbench.skill_runtime, "context", lambda *a, **k: ("", {})), \
             mock.patch.object(workbench, "_json_text", fake_json), \
             mock.patch.object(workbench, "_record_skill", lambda *a, **k: None), \
             mock.patch.dict("os.environ", environ):
            workbench._framework("标题", "人格", "",
                                 session={"topic_research": {"sources": [{"title": "s"}]}})
        return captured

    def test_outline_model_is_configurable_per_node(self):
        captured = self._run({"WECHAT_OUTLINE_MODEL": "fast-model"})
        self.assertEqual("fast-model", captured.get("model"))

    def test_outline_model_defaults_to_the_pipeline_model(self):
        captured = self._run({})
        self.assertIsNone(captured.get("model"))


class NodeTimingTests(unittest.TestCase):
    def test_execute_node_records_duration_and_node(self):
        events = []
        with mock.patch.object(workflow_engine, "_execute_node", lambda w, n: {"ok": True}), \
             mock.patch.object(workflow_engine, "log_event",
                               lambda name, **kw: events.append((name, kw))):
            result = workflow_engine.execute_node({"id": "w1", "user_id": "u1"}, "draft")
        self.assertEqual({"ok": True}, result)
        self.assertEqual("workflow.node", events[0][0])
        self.assertEqual("draft", events[0][1]["node"])
        self.assertEqual("w1", events[0][1]["workflow_id"])
        self.assertIn("duration_ms", events[0][1])
        self.assertEqual("ok", events[0][1]["status"])

    def test_execute_node_records_failure_and_reraises(self):
        events = []

        def boom(workflow, node):
            raise RuntimeError("node failed")

        with mock.patch.object(workflow_engine, "_execute_node", boom), \
             mock.patch.object(workflow_engine, "log_event",
                               lambda name, **kw: events.append((name, kw))):
            with self.assertRaises(RuntimeError):
                workflow_engine.execute_node({"id": "w1"}, "draft")
        self.assertEqual("RuntimeError", events[0][1]["status"])
        self.assertEqual("draft", events[0][1]["node"])


class TextRetryTests(unittest.TestCase):
    """上游流中断（transient）要重试，一次抖动不该废掉整篇。"""

    def _run(self, script, attempts="3"):
        from server.providers import ProviderRequestError  # noqa: F401  (type documented in stubs)
        _FlakyService.calls = 0
        _FlakyService.script = script
        with mock.patch("server.providers.OpenAICompatibleProvider", _FakeProvider), \
             mock.patch("server.providers.ModelService", _FlakyService), \
             mock.patch.dict("os.environ", {"WECHAT_TEXT_API_KEY": "k",
                                            "WECHAT_TEXT_ATTEMPTS": attempts}):
            return workbench._text("提示")

    def test_transient_failure_is_retried(self):
        from server.providers import ProviderRequestError

        def script(call_no):
            if call_no <= 1:
                raise ProviderRequestError("Upstream response stream was interrupted",
                                           code="provider_unavailable", transient=True)
            return _FakeResponse()

        self.assertEqual("正文", self._run(script))

    def test_permanent_failure_is_not_retried(self):
        from server.providers import ProviderRequestError

        def script(call_no):
            raise ProviderRequestError("bad api key", code="invalid_response", transient=False)

        with self.assertRaises(workbench.ProviderError):
            self._run(script)
        self.assertEqual(1, _FlakyService.calls)


if __name__ == "__main__":
    unittest.main()
