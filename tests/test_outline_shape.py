import unittest
from tests import support  # noqa
from server import skill_host

PROD_SHAPE = [
 {"content": ["a", "b"], "purpose": "解决素材发现后无法及时留下的问题", 
  "section": "方法一：建立统一的低摩擦收集入口", "evidence_basis": ["c3", "c4"], "reader_progress": "x"},
 {"content": ["c"], "purpose": "让判断可复用", "section": "方法二：把素材写成判断", 
  "evidence_basis": "c5", "reader_progress": "y"},
]

class RealShapeTests(unittest.TestCase):
    def test_production_style_outline_is_not_dropped(self):
        class State: outline = PROD_SHAPE
        sections = skill_host.outline_sections(State())
        self.assertEqual(2, len(sections), sections)
        self.assertIn("低摩擦收集入口", sections[0]["heading"])
        self.assertIn("无法及时留下", sections[0]["claim"])
        self.assertEqual("c3, c4", sections[0]["evidence"])

    def test_frame_keeps_headings(self):
        class State:
            outline = PROD_SHAPE
            writing_strategy = {"reader_question": "q"}
            angle = ""
            selected_title = "t"
        frame = skill_host.frame_from_state(State())
        self.assertEqual(2, len(frame["outline"]))
        self.assertTrue(frame["outline"][0].startswith("方法一"))

if __name__ == '__main__':
    unittest.main()
