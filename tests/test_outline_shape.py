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
    def test_specific_titles_and_plans_override_repeated_section_labels(self):
        class State:
            outline = [
                {'section': '三个样本', 'section_title': '样本一：客户咨询回复',
                 'content_plan': '展示一段客户问题和可核验的回复。'},
                {'section': '三个样本', 'section_title': '样本二：产品介绍页',
                 'content_plan': '展示一页产品介绍及修改依据。'},
            ]
        sections = skill_host.outline_sections(State())
        self.assertEqual(['样本一：客户咨询回复', '样本二：产品介绍页'],
                         [item['heading'] for item in sections])
        self.assertIn('客户问题', sections[0]['claim'])

    def test_repeated_labels_and_placeholders_fail_quality_gate(self):
        bad = {'outline': [
            {'section': '三个样本', 'content_plan': '第一个样本'},
            {'section': '三个样本', 'content_plan': '第二个样本'},
        ], 'writing_strategy': {'article_type': 'tutorial'}}
        self.assertIn('重复', skill_host.outline_quality_issue(bad))
        bad['outline'][1]['section_title'] = '样本二：{待选类型B}'
        self.assertIn('占位符', skill_host.outline_quality_issue(bad))

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
