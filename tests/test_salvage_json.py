import unittest
from server import workbench

CASES = {
 "full_width": '{"outline": [{"heading"：“全角引号标题”，"claim"：“原因”}]}',
 "truncated": '{"outline": [{"heading": "标题", "claim": "论',
 "mid_broken": '{"outline": [{"heading": "标题" "claim": "缺逗号"}]}',
}

class SalvageTests(unittest.TestCase):
    def test_full_width_punctuation_is_repaired(self):
        data = workbench._salvage_json(CASES["full_width"])
        self.assertIsNotNone(data)
        self.assertEqual("全角引号标题", data["outline"][0]["heading"])

    def test_truncated_object_is_closed(self):
        data = workbench._salvage_json(CASES["truncated"])
        self.assertIsNotNone(data)
        self.assertEqual(1, len(data["outline"]))

    def test_missing_comma_returns_none_instead_of_raising(self):
        workbench._salvage_json(CASES["mid_broken"])  # must not raise

    def test_empty_input_is_none(self):
        self.assertIsNone(workbench._salvage_json(""))

if __name__ == '__main__':
    unittest.main()
