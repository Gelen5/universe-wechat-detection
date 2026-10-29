"""The strategy node must take the skill's contract, not a label list.

The skill declares ``outline: array<object>``; the web prompt had degraded it to
``array<string>``, which can only carry labels — that is why every article came
back with the same 「判断一/分节二/开篇切入」 skeleton. These tests also pin that
the node really reads the skill files, so a future rewrite cannot quietly go back
to a hand-written prompt.
"""
import unittest
from unittest.mock import patch

from tests import support  # noqa: F401 - isolated account database
from server import workbench

SKILL_STRATEGY_MARKER = 'SKILL_STRATEGY_RULES_MARKER'
SKILL_FRAMEWORKS_MARKER = 'SKILL_FRAMEWORKS_MARKER'


def _call_frame(payloads):
    prompts = []
    with patch.object(workbench, '_require_skill'), \
         patch.object(workbench, '_record_skill'), \
         patch.object(workbench.skill_runtime, 'context',
                      return_value=(SKILL_FRAMEWORKS_MARKER, [])), \
         patch.object(workbench.skill_runtime, 'node_rules',
                      return_value=(SKILL_STRATEGY_MARKER, [])), \
         patch.object(workbench.workbench_research, 'search', return_value={}), \
         patch.object(workbench, '_json_text',
                      side_effect=lambda prompt, **kw: prompts.append(prompt) or payloads.pop(0)):
        frame = workbench._framework('主题', '观点', '写一篇观点文')
    return frame, prompts


class OutlineContractTests(unittest.TestCase):
    def test_sections_carry_a_claim_and_evidence(self):
        frame, _ = _call_frame([{
            'name': '按材料推进',
            'outline': [
                {'heading': '发了三十篇没起色，先看每一篇是否回答了同一个读者问题',
                 'claim': '篇数不等于方向验证', 'evidence': '用户提供的后台数据'},
                {'heading': '标题承诺与正文交付不一致，读者第二轮就不会再点开',
                 'claim': '标题与正文必须对齐', 'evidence': 'none'},
            ],
            'writing_strategy': {'article_type': 'opinion'},
        }])
        self.assertEqual('specific', frame['outline_quality'])
        self.assertEqual(2, len(frame['outline_sections']))
        self.assertEqual('篇数不等于方向验证', frame['outline_sections'][0]['claim'])
        # The UI and older sessions still read a string array.
        self.assertTrue(all(isinstance(item, str) for item in frame['outline']))
        self.assertIn('发了三十篇没起色', frame['outline'][0])

    def test_template_labels_are_sent_back_once(self):
        frame, prompts = _call_frame([
            {'outline': [{'heading': '判断一：背景'}, {'heading': '判断二：方法'}],
             'writing_strategy': {'article_type': 'opinion'}},
            {'outline': [
                {'heading': '读者记不住只讲道理的文章，因为每段都在重复同一个判断',
                 'claim': '具体性决定记忆', 'evidence': '用户素材'},
                {'heading': '把结论改成可以验证的动作，读者才知道下一步做什么',
                 'claim': '动作可执行', 'evidence': 'none'},
            ], 'writing_strategy': {'article_type': 'opinion'}},
        ])
        self.assertEqual(2, len(prompts))
        self.assertIn('判断一', prompts[1])          # the retry names what failed
        self.assertEqual('specific', frame['outline_quality'])
        self.assertIn('可以验证的动作', frame['outline'][1])

    def test_a_second_template_answer_is_accepted_but_marked(self):
        payload = {'outline': [{'heading': '分节一：开场'}, {'heading': '分节二：结尾'}],
                   'writing_strategy': {'article_type': 'opinion'}}
        frame, _ = _call_frame([payload, dict(payload)])
        self.assertEqual('template', frame['outline_quality'])

    def test_plain_string_outlines_still_load(self):
        frame, _ = _call_frame([{
            'outline': ['读者为什么在第三段就走了：开头没有交付具体信息',
                        '把每一段的结论写成可以核对的事实，而不是情绪'],
            'writing_strategy': {'article_type': 'opinion'},
        }])
        self.assertEqual(2, len(frame['outline_sections']))
        self.assertEqual('none', frame['outline_sections'][0]['evidence'])


class SkillWiringTests(unittest.TestCase):
    def test_framework_prompt_really_contains_the_skill_files(self):
        _, prompts = _call_frame([{
            'outline': [{'heading': '读者需要的是能核对的判断，不是漂亮的排比句'},
                        {'heading': '每一节都要说明它依赖哪一条材料'}],
            'writing_strategy': {'article_type': 'opinion'},
        }])
        prompt = prompts[0]
        self.assertIn(SKILL_FRAMEWORKS_MARKER, prompt,
                      'frameworks.md no longer reaches the outline prompt')
        self.assertIn(SKILL_STRATEGY_MARKER, prompt,
                      'human-writing-strategy.md no longer reaches the outline prompt')

    def test_contract_asks_for_objects_not_labels(self):
        _, prompts = _call_frame([{
            'outline': [{'heading': '第一句就是这篇的判断'}, {'heading': '第二句说明它依赖哪条材料'}],
            'writing_strategy': {}}])
        self.assertIn('"heading"', prompts[0])
        self.assertIn('"claim"', prompts[0])
        self.assertIn('"evidence"', prompts[0])


if __name__ == '__main__':
    unittest.main()
