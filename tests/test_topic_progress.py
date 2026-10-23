"""选题必须在长等待中回报进度，而不是只有一句"正在执行"。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from server import workbench


class TopicProgressTests(unittest.TestCase):
    def run_with_progress(self, hotspots=None, topics=None):
        steps = []

        def progress(step, detail=None):
            steps.append((step, dict(detail or {})))

        session = {}
        topics = topics or [{"title": f"方向{i}"} for i in range(1, 7)]
        with patch.object(workbench, "_require_skill"), \
                patch.object(workbench.skill_runtime, "context", return_value=("规则", [])), \
                patch.object(workbench.skill_runtime, "script",
                             return_value=hotspots if hotspots is not None else [{"title": "热点"}]), \
                patch.object(workbench.workbench_research, "search",
                             return_value={"status": "ok", "sources": [{"url": "https://a"}], "runs": []}), \
                patch.object(workbench.workbench_research, "history",
                             return_value={"status": "unavailable", "titles": []}), \
                patch.object(workbench, "_json_text", return_value={"topics": topics}):
            workbench._suggestions("AI 工具", "观察者", session, progress)
        return steps

    def test_progress_covers_every_slow_phase(self):
        steps = self.run_with_progress()
        names = [name for name, _ in steps]
        self.assertIn("hotspots", names)
        self.assertIn("search", names)
        self.assertIn("generating", names)
        self.assertIn("generated", names)

    def test_hotspot_count_is_reported(self):
        steps = self.run_with_progress(hotspots=[{"title": "a"}, {"title": "b"}])
        final = [detail for name, detail in steps if name == "hotspots"][-1]
        self.assertEqual(2, final["count"])
        self.assertEqual("available", final["status"])

    def test_degraded_hotspots_are_reported_not_hidden(self):
        steps = []
        with patch.object(workbench, "_require_skill"), \
                patch.object(workbench.skill_runtime, "context", return_value=("规则", [])), \
                patch.object(workbench.skill_runtime, "script", side_effect=RuntimeError("timeout")), \
                patch.object(workbench.workbench_research, "search", return_value={"status": "unavailable"}), \
                patch.object(workbench.workbench_research, "history",
                             return_value={"status": "unavailable", "titles": []}), \
                patch.object(workbench, "_json_text",
                             return_value={"topics": [{"title": f"方向{i}"} for i in range(6)]}):
            workbench._suggestions("AI", "观察者", {}, lambda step, detail=None: steps.append((step, detail)))
        hotspot = [detail for name, detail in steps if name == "hotspots"][-1]
        self.assertEqual("unavailable", hotspot["status"])

    def test_generated_count_is_reported(self):
        steps = self.run_with_progress()
        generated = [detail for name, detail in steps if name == "generated"][-1]
        self.assertEqual(6, generated["count"])

    def test_progress_callback_failure_does_not_break_the_stage(self):
        def broken(step, detail=None):
            raise RuntimeError("client gone")

        with patch.object(workbench, "_require_skill"), \
                patch.object(workbench.skill_runtime, "context", return_value=("规则", [])), \
                patch.object(workbench.skill_runtime, "script", return_value=[]), \
                patch.object(workbench.workbench_research, "search", return_value={"status": "unavailable"}), \
                patch.object(workbench.workbench_research, "history",
                             return_value={"status": "unavailable", "titles": []}), \
                patch.object(workbench, "_json_text",
                             return_value={"topics": [{"title": f"方向{i}"} for i in range(6)]}):
            result = workbench._suggestions("AI", "观察者", {}, broken)
        self.assertEqual(6, len(result))


if __name__ == "__main__":
    unittest.main()
