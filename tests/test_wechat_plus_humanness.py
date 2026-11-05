"""Skill-native humanness diagnostics and the local-revision guard."""
import subprocess
from unittest.mock import patch

from server import wechat_plus_humanness as humanness
from server import wechat_plus_runtime as runtime
from tests.test_wechat_plus_service import REWRITE_DRAFT, STEP_DRAFT


def test_diagnose_returns_the_skill_report(tmp_path):
    report = humanness.diagnose(STEP_DRAFT, output_dir=tmp_path)
    assert report['available'] is True
    assert isinstance(report['final_score'], (int, float))
    assert {'statistical', 'pattern', 'llm'} <= set(report['layers'])
    assert isinstance(report['repair_plan'], list)
    assert (tmp_path / 'draft_for_score.md').is_file()


def test_diagnose_failure_is_advisory(tmp_path):
    failed = subprocess.CompletedProcess(['humanness_score.py'], 1, '', 'boom')
    with patch.object(humanness.subprocess, 'run', return_value=failed):
        report = humanness.diagnose(STEP_DRAFT, output_dir=tmp_path)
    assert report['available'] is False
    assert 'boom' in report['reason']


def test_guard_rejects_a_full_rewrite():
    result = {'reader_simulation': [], 'revision_plan': [],
              'revised_draft': REWRITE_DRAFT}
    guarded, info = runtime.guard_revision({'draft': STEP_DRAFT}, result)
    assert 'revised_draft' not in guarded
    assert info['revised_draft_rejected'] == 'too_much_rewrite'
    assert info['applied'] is False
    assert info['revision_similarity'] < 0.85


def test_guard_accepts_a_local_revision():
    paragraphs = STEP_DRAFT.split('\n\n')
    revised = list(paragraphs)
    revised[2] = revised[2] + ' 这一段补一个具体动作。'
    revised[4] = revised[4] + ' 这一段补一句判断。'
    revised_text = '\n\n'.join(revised)
    guarded, info = runtime.guard_revision({'draft': STEP_DRAFT},
                                           {'revised_draft': revised_text})
    assert guarded['revised_draft'] == revised_text
    assert info['applied'] is True
    assert info['revision_similarity'] >= 0.85


def test_guard_rejects_missing_protected_content():
    source = ('# 标题\n\n' + '这是一段足够长的正文，用来保证相似度很高。' * 20
              + '详见 https://example.com/a 。\n\n结尾。')
    revised = source.replace(' https://example.com/a ', ' ')
    guarded, info = runtime.guard_revision({'draft': source},
                                           {'revised_draft': revised})
    assert 'revised_draft' not in guarded
    assert info['revised_draft_rejected'] == 'protected_content_lost'
    assert 'https://example.com/a' in ' '.join(info['missing_protected'])
