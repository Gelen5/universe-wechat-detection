"""选题不能在外部热点不可用时整条中断。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from server import workbench


class TopicResilienceTests(unittest.TestCase):
    def run_suggestions(self, hotspots, topics, history=None):
        session = {}
        with patch.object(workbench, "_require_skill"), \
                patch.object(workbench.skill_runtime, "context", return_value=("选题规则", [])), \
                patch.object(workbench.skill_runtime, "script", **hotspots), \
                patch.object(workbench.workbench_research, "search",
                             return_value={"status": "unavailable", "sources": []}), \
                patch.object(workbench.workbench_research, "history",
                             return_value=history or {"status": "unavailable", "titles": []}), \
                patch.object(workbench, "_json_text", return_value={"topics": topics}):
            return workbench._suggestions("AI 工具实测", "深度观察者", session), session

    def test_hotspot_timeout_degrades_instead_of_failing(self):
        result, session = self.run_suggestions(
            {"side_effect": RuntimeError("fetch_hotspots.py 执行失败：timeout")},
            [{"title": f"方向{i}"} for i in range(1, 7)],
        )
        self.assertEqual(6, len(result))
        self.assertEqual("unavailable", session["hotspot_status"])

    def test_hotspot_returns_non_list_degrades(self):
        result, session = self.run_suggestions(
            {"return_value": {"unexpected": True}},
            [{"title": f"方向{i}"} for i in range(1, 7)],
        )
        self.assertEqual(6, len(result))
        self.assertEqual("unavailable", session["hotspot_status"])

    def test_six_topics_are_enough(self):
        result, _ = self.run_suggestions(
            {"return_value": [{"title": "热点", "sources": ["baidu"]}]},
            [{"title": f"方向{i}"} for i in range(1, 7)],
        )
        self.assertEqual(6, len(result))
        self.assertEqual([1, 2, 3, 4, 5, 6], [item["id"] for item in result])

    def test_short_answer_still_fails_with_actionable_text(self):
        with self.assertRaises(workbench.ProviderError) as caught:
            self.run_suggestions(
                {"return_value": []},
                [{"title": f"方向{i}"} for i in range(1, 4)],
            )
        self.assertIn("低于最低要求", str(caught.exception))

    def test_history_overlap_does_not_block_the_result(self):
        result, _ = self.run_suggestions(
            {"return_value": []},
            [{"title": f"历史老选题{i}"} for i in range(1, 7)],
            history={"status": "checked", "titles": [f"历史老选题{i}" for i in range(1, 7)]},
        )
        self.assertEqual(6, len(result))
        self.assertTrue(all(item.get("note") for item in result))

    def test_empty_items_are_dropped_not_fatal(self):
        result, _ = self.run_suggestions(
            {"return_value": []},
            [{"title": ""}, *[{"title": f"方向{i}"} for i in range(1, 7)]],
        )
        self.assertEqual(6, len(result))


if __name__ == "__main__":
    unittest.main()
