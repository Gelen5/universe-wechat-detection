"""Tests for the extracted stage executors and the ArticleState -> session projection."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from server import skill_article_adapter, workbench

VENDORED = Path(__file__).resolve().parents[1] / "vendor" / "skills" / "weChat-autoCreate"


def _session(**overrides):
    base = {
        "id": "s1", "user_id": "u1", "mode": "interactive", "persona": "深度观察者",
        "topic": "", "framework": None, "article": "", "suggestions": [{"title": "方向甲"}],
        "image_policy": "none", "image_plan": None, "images": [],
        "typeset_html": "", "status": "ready_for_review", "current_step": 1,
    }
    base.update(overrides)
    return base


class StageExecutorTests(unittest.TestCase):
    def _run(self, session, target, selection=None):
        calls: list[str] = []

        def framework(topic, persona, brief, sess):
            calls.append("framework")
            return {"name": "SCQA", "outline": ["一", "二"]}

        def draft(topic, frame, persona, brief, sess):
            calls.append("draft")
            return "# 标题\n正文"

        def review(article, sess):
            calls.append("review")
            return article, {"status": "passed"}

        with mock.patch.object(workbench, "_framework", framework), \
             mock.patch.object(workbench, "_draft", draft), \
             mock.patch.object(workbench, "_review", review), \
             mock.patch.object(workbench, "_score", lambda a, s: {"status": "success"}), \
             mock.patch.object(workbench, "_review_is_current", lambda s: bool(s.get("review"))), \
             mock.patch.object(workbench, "_require_skill_steps", lambda s, t: None), \
             mock.patch.object(workbench, "_session_view", lambda s: dict(s)), \
             mock.patch.object(workbench.skill_runtime, "brief", lambda s: "要求"):
            workbench._advance(session, target, selection)
        return calls

    def test_reaching_a_later_step_runs_the_earlier_nodes_in_order(self):
        session = _session()
        calls = self._run(session, 4)
        self.assertEqual(["framework", "draft", "review"], calls)
        # 复核节点会用正文的一级标题回写主题，这是既有行为。
        self.assertEqual("标题", session["topic"])
        self.assertEqual({"name": "SCQA", "outline": ["一", "二"]}, session["framework"])
        self.assertEqual("# 标题\n正文", session["article"])
        self.assertEqual(4, session["current_step"])

    def test_finished_nodes_are_not_recomputed(self):
        done = _session(framework={"name": "SCQA", "outline": ["一"]},
                        article="# 已写\n正文", review={"status": "passed"})
        calls = self._run(done, 4)
        self.assertEqual([], calls, "已完成的节点不应重复调用模型")

    def test_selection_falls_back_to_the_first_candidate(self):
        session = _session(suggestions=[{"title": "甲"}, {"title": "乙"}])
        self._run(session, 2, selection=2)
        self.assertEqual("乙", session["topic"])

    def test_outline_without_candidates_is_a_clear_error(self):
        session = _session(suggestions=[])
        with self.assertRaises(workbench.ProviderError) as caught:
            self._run(session, 2)
        self.assertIn("选题", str(caught.exception))

    def test_cancelled_session_aborts_before_any_node(self):
        session = _session()
        workbench.CANCEL_REQUESTS.add("s1")
        try:
            with self.assertRaises(workbench.ProviderError):
                self._run(session, 4)
        finally:
            workbench.CANCEL_REQUESTS.discard("s1")


class HydrateSessionTests(unittest.TestCase):
    def setUp(self):
        if not VENDORED.is_dir():
            self.skipTest("vendored skill missing")
        if str(VENDORED) not in sys.path:
            sys.path.insert(0, str(VENDORED))
        self._patch = mock.patch.object(workbench, "SKILL_DIR", VENDORED)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def _payload(self, *, draft="", outline=None, title=""):
        from toolkit import article_state as state_mod, article_workflow as wf

        state = wf.new_article_state("写一篇关于老店关闭的文章", topic=title)
        if title:
            state.selected_title = title
        if outline:
            state.outline = [{"content": line} for line in outline]
        if draft:
            state.draft = draft
        return state.to_dict()

    def test_missing_fields_are_copied_from_the_state(self):
        session = _session()
        result = skill_article_adapter.hydrate_session(
            session, self._payload(draft="# 标题\n正文", outline=["开头", "结尾"], title="老店为什么关了"))
        self.assertEqual(["article", "framework", "topic"], result["restored"])
        self.assertEqual("# 标题\n正文", session["article"])
        self.assertEqual(["开头", "结尾"], session["framework"]["outline"])
        self.assertEqual("老店为什么关了", session["topic"])

    def test_existing_session_values_win(self):
        session = _session(article="# 本地改过的稿", framework={"name": "AIDA", "outline": ["本地"]},
                           topic="本地标题")
        result = skill_article_adapter.hydrate_session(
            session, self._payload(draft="# 状态里的稿", outline=["状态"], title="状态标题"))
        self.assertEqual([], result["restored"])
        self.assertEqual("# 本地改过的稿", session["article"])
        self.assertEqual("本地标题", session["topic"])

    def test_empty_state_restores_nothing(self):
        session = _session()
        result = skill_article_adapter.hydrate_session(session, self._payload())
        self.assertEqual([], result["restored"])
        self.assertEqual("", session["article"])


if __name__ == "__main__":
    unittest.main()
