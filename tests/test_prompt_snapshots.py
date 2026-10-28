"""Golden snapshots of the assembled writing prompts.

Moving rule text between files must not change what the model receives.
Regenerate deliberately with UPDATE_PROMPT_GOLDEN=1 only when a prompt change
has been reviewed for quality.
"""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import support  # noqa: F401 - isolated account database
from server import qihaoshou, workbench, writing_guidance

GOLDEN = Path(__file__).with_name('golden') / 'writing_prompts.json'

DRAFT_CASES = {
    'tutorial-default-length': ({'article_type': 'tutorial', 'reader_question': '怎么做'}, '公众号 Skill 操作教程'),
    'emotional-explicit-length': ({'article_type': 'emotional_opinion'}, '面向夫妻的情感观点，900–1100字，不编造对白'),
    'opinion': ({'article_type': 'opinion'}, 'AI 工具的个人观点'),
    'news': ({'article_type': 'news'}, '保留资讯来源'),
    'story': ({'article_type': 'story'}, '根据我提供的真实经历写故事'),
    'unspecified': ({}, ''),
}

ONE_CLICK_BASE = {
    'reference': '用户粘贴的参考材料。', 'reference_url': '', 'mode': 'custom',
    'topic': '如何写好公众号开头', 'audience': '新手作者', 'style': 'professional',
    'length': 1500, 'angle': '从读者问题切入', 'outline': '一、二、三',
    'source_notes': '无', 'instructions': '少用套话',
}


def _draft_prompt(strategy, requirements):
    frame = {'name': '按材料推进', 'outline': ['开头', '展开'], 'research': {},
             'writing_strategy': strategy}
    prompts = []
    with patch.object(workbench, '_require_skill'), \
         patch.object(workbench, '_record_skill'), \
         patch.object(workbench.skill_runtime, 'length_issue', return_value=None), \
         patch.object(workbench, '_text', side_effect=lambda p, **kw: prompts.append(p) or '# 标题\n正文'):
        workbench._draft('主题', frame, '语气', requirements, {})
    return prompts[0]


def snapshot():
    data = {'writing_guidance': {
        'GUIDANCE': writing_guidance.GUIDANCE,
        'draft_quality_rules': writing_guidance.draft_quality_rules(),
        'optional_preferences': writing_guidance.optional_preferences(
            {'writing_goal': '目标', 'content_form': '教程', 'author_material': '素材'}),
        'draft_strategy_v2': {k: writing_guidance.draft_strategy_v2(s, r) for k, (s, r) in DRAFT_CASES.items()},
    }}
    data['agent_draft'] = {k: _draft_prompt(s, r) for k, (s, r) in DRAFT_CASES.items()}
    data['one_click_draft'] = {
        style: qihaoshou.draft_prompt(dict(ONE_CLICK_BASE, style=style)) for style in sorted(qihaoshou.STYLES)
    }
    return data


def _normalized(value):
    """Rule files are stored with LF; a Windows worktree checks them out as CRLF.

    Prompt *content* is identical either way, so snapshots compare normalized
    text instead of pinning the checkout's line endings.
    """
    if isinstance(value, str):
        return value.replace('\r\n', '\n')
    if isinstance(value, dict):
        return {k: _normalized(v) for k, v in value.items()}
    return value


class PromptSnapshotTests(unittest.TestCase):
    def test_assembled_prompts_match_golden(self):
        current = _normalized(snapshot())
        if os.getenv('UPDATE_PROMPT_GOLDEN') == '1' or not GOLDEN.exists():
            GOLDEN.parent.mkdir(exist_ok=True)
            GOLDEN.write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding='utf-8')
            self.skipTest('golden regenerated')
        expected = json.loads(GOLDEN.read_text(encoding='utf-8'))
        for group, rows in expected.items():
            for key, value in rows.items():
                with self.subTest(group=group, key=key):
                    self.assertEqual(value, current[group][key])


if __name__ == '__main__':
    unittest.main()
