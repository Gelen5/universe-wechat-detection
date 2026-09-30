from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.integrations.easel.harness import UniverseNativeHarness
from server.integrations.easel.harness.schemas import RunContext
from server.integrations.easel.native.skill_loader import NativeSkillLoader


class EaselNativeTests(unittest.TestCase):
    def test_loader_parses_yaml_and_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skill = root / "example-skill"
            (skill / "references").mkdir(parents=True)
            (skill / "scripts").mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: Example\ndescription: Test skill\nlayer: plan\n---\n\nDo the work.\n",
                encoding="utf-8",
            )
            (skill / "references" / "guide.md").write_text("Guide", encoding="utf-8")
            (skill / "scripts" / "process.py").write_text("print(1)", encoding="utf-8")
            loader = NativeSkillLoader(root)
            loaded = loader.load("example-skill")
            self.assertEqual(loaded.category, "plan")
            self.assertEqual(loaded.instructions, "Do the work.")
            self.assertEqual(len(loaded.references), 1)
            self.assertEqual(len(loaded.scripts), 1)
            with self.assertRaises(ValueError):
                loader.load("../escape")

    def test_native_reuses_universe_tool_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skill = root / "simple"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: Simple\nlayer: produce\n---\nWrite one sentence.\n", encoding="utf-8")
            loaded = NativeSkillLoader(root).load("simple")
            context = RunContext("user", "run", "conversation", root, root)
            with patch("server.integrations.easel.harness.native.run_tool_loop", return_value="Done") as loop:
                result = asyncio.run(UniverseNativeHarness(object()).execute(
                    run_context=context, skill=loaded, input_data="Hello", profile={},
                    attachments=[], tools={},
                ))
            self.assertEqual(result.text, "Done")
            self.assertEqual(loop.call_args.kwargs["skill_id"], "easel:simple")
            self.assertEqual(loop.call_args.kwargs["tools"], {})


if __name__ == "__main__":
    unittest.main()
