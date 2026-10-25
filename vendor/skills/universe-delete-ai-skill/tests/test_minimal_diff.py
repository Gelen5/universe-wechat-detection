import unittest

from scripts.verify_minimal_diff import verify


class MinimalDiffTests(unittest.TestCase):
    def test_allows_change_inside_flagged_sentence(self) -> None:
        original = "说白了，这个方案成本太高。\n\n这句话保持不变。"
        revision = "这个方案成本太高。\n\n这句话保持不变。"
        self.assertEqual(verify(original, revision)["status"], "pass")

    def test_rejects_change_to_unmatched_sentence(self) -> None:
        original = "说白了，这个方案成本太高。\n\n这句话保持不变。"
        revision = "这个方案成本太高。\n\n这句话被顺手改了。"
        result = verify(original, revision)
        self.assertEqual(result["status"], "review_required")
        self.assertTrue(result["violations"])

    def test_rejects_any_change_when_no_rule_matches(self) -> None:
        result = verify("今天下雨了。", "今天下过雨。")
        self.assertEqual(result["status"], "review_required")

    def test_rejects_insertion_after_flagged_sentence_boundary(self) -> None:
        original = "说白了，这个方案成本太高。\n\n这句话保持不变。"
        revision = "说白了，这个方案成本太高。新增一句。\n\n这句话保持不变。"
        self.assertEqual(verify(original, revision)["status"], "review_required")


if __name__ == "__main__":
    unittest.main()
