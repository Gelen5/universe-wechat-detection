import unittest
from pathlib import Path
from unittest.mock import patch
from tests import support  # noqa
from server import skill_host, workbench

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / 'vendor' / 'skills' / 'weChat-autoCreate'


class TruncatedJsonTests(unittest.TestCase):
    def setUp(self):
        self.p = patch.object(workbench, 'SKILL_DIR', SKILL)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_cut_off_outline_is_repaired(self):
        _s, _w, runtime = skill_host._modules()
        data = runtime.parse_result('{"outline": [{"section": "开头：反差判断", "purpose": "切入"}')
        self.assertEqual(1, len(data["outline"]))
        self.assertEqual("开头：反差判断", data["outline"][0]["section"])

    def test_cut_off_mid_string_is_closed(self):
        _s, _w, runtime = skill_host._modules()
        data = runtime.parse_result('{"outline": [{"section": "方法一：按问题收，不按')
        self.assertEqual(1, len(data["outline"]))


if __name__ == "__main__":
    unittest.main()
