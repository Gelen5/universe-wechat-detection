import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support  # noqa: F401
from server import skill_host, workbench


class OutlineReopenTests(unittest.TestCase):
    def test_passed_bad_outline_is_regenerated(self):
        good = {'outline': [
            {'section_title': '先用客户问题做回复样本', 'content_plan': '展示问题与回复。'},
            {'section_title': '再用产品资料做介绍页', 'content_plan': '展示结构与核对方法。'},
        ], 'writing_strategy': {'article_type': 'tutorial'}}
        skill_dir = Path(__file__).resolve().parents[1] / 'vendor' / 'skills' / 'weChat-autoCreate'
        with patch.object(workbench, 'SKILL_DIR', skill_dir), \
             patch.object(workbench, '_text', return_value=json.dumps(good, ensure_ascii=False)) as model:
            state = skill_host.new_state('写一篇文章')
            for node in ('intent', 'topic', 'research', 'strategy'):
                state.nodes[node].status = 'passed'
            state.outline = [{'section': '三个样本', 'content_plan': '甲'},
                             {'section': '三个样本', 'content_plan': '乙'}]
            state.writing_strategy = {'article_type': 'tutorial'}
            skill_host.run_to(state, 'strategy')
        self.assertEqual('passed', state.nodes['strategy'].status)
        self.assertEqual(1, model.call_count)
        self.assertEqual('先用客户问题做回复样本', skill_host.outline_sections(state)[0]['heading'])


if __name__ == '__main__':
    unittest.main()
