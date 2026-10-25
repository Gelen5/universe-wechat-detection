import json
import tempfile
import unittest
from pathlib import Path

from scripts.check_protected_spans import check_manifest, collect


class ProtectedSpanTests(unittest.TestCase):
    def test_collects_qualifiers_and_named_entity_hints(self) -> None:
        spans = collect("据说北京大学实验室可能在2026年完成测试。")
        self.assertIn("据说", spans["qualifier"])
        self.assertIn("可能", spans["qualifier"])
        self.assertTrue(any("北京大学" in value for value in spans["named_entity_hint"]))

    def test_collects_numbers_attached_to_chinese_words(self) -> None:
        spans = collect("毕业10年后，工资涨到8000元，处理时间是40分钟。")
        self.assertIn("10年", spans["number_or_date"])
        self.assertIn("8000元", spans["number_or_date"])
        self.assertIn("40分钟", spans["number_or_date"])

    def test_manifest_reports_missing_and_forbidden_content(self) -> None:
        manifest = {
            "required": {
                "人物": ["李清照", "张汝舟"],
                "动作": ["告发"],
            },
            "forbidden_additions": ["孩子"],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "facts.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            result = check_manifest("李清照离开了张汝舟，还提到了孩子。", path)

        self.assertEqual(result["required_missing"]["动作"], ["告发"])
        self.assertEqual(result["forbidden_found"], ["孩子"])


if __name__ == "__main__":
    unittest.main()
