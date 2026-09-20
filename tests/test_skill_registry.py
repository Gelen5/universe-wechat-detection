from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from server.skills.loader import SkillManifestError, load_manifest
from server.skills.registry import DEFAULT_ROOT, SkillRegistry
from server.skills.runtime import load_instructions


class SkillRegistryTests(unittest.TestCase):
    def test_discovers_all_current_skills(self):
        registry = SkillRegistry((DEFAULT_ROOT,)).reload()
        ids = {item.id for item in registry.list()}
        self.assertEqual({"wechat_writer", "xiaohongshu_creator", "wechat_tie_tu",
                          "wechat_hit_detector", "wechat_account_analyzer", "morning_blessing"}, ids)

    def test_router_catalog_is_lightweight(self):
        catalog = SkillRegistry((DEFAULT_ROOT,)).reload().router_catalog()
        self.assertTrue(catalog)
        self.assertEqual({"id", "name", "description", "capabilities"}, set(catalog[0]))
        self.assertNotIn("tools", catalog[0])

    def test_full_instructions_load_only_for_selected_skill(self):
        registry = SkillRegistry((DEFAULT_ROOT,)).reload()
        content, path = load_instructions("morning_blessing", registry=registry)
        self.assertIn("早安", content)
        self.assertEqual("SKILL.md", path.name)

    def test_every_tool_exposes_actionable_json_schema(self):
        registry = SkillRegistry((DEFAULT_ROOT,)).reload()
        for skill in registry.list():
            for tool in skill.tools:
                self.assertEqual("object", tool.parameters.get("type"))
                self.assertTrue(tool.parameters.get("properties"), f"{skill.id}.{tool.name}")

    def test_rejects_duplicate_skill_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("a", "b"):
                directory = root / name
                directory.mkdir()
                (directory / "SKILL.md").write_text("# test", encoding="utf-8")
                (directory / "skill.json").write_text(json.dumps({
                    "id": "same_skill", "name": name, "version": "1", "description": "test",
                }), encoding="utf-8")
            with self.assertRaises(ValueError):
                SkillRegistry((root,)).reload()

    def test_rejects_manifest_without_skill_instructions(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "skill.json"
            path.write_text(json.dumps({"id": "missing_skill", "name": "Missing",
                                        "version": "1", "description": "test"}), encoding="utf-8")
            with self.assertRaises(SkillManifestError):
                load_manifest(path)

    def test_untrusted_skill_is_not_routable_or_executable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            directory = root / "third_party"
            directory.mkdir()
            (directory / "SKILL.md").write_text("# external", encoding="utf-8")
            (directory / "skill.json").write_text(json.dumps({
                "id": "third_party", "name": "External", "version": "1",
                "description": "not approved for in-process execution",
            }), encoding="utf-8")
            registry = SkillRegistry((root,)).reload()
            self.assertFalse(registry.get("third_party").trusted)
            self.assertEqual([], registry.router_catalog())
            with self.assertRaises(PermissionError):
                registry.executable("third_party")


if __name__ == "__main__":
    unittest.main()
