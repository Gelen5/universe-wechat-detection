from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from server import skill_article_adapter as adapter, skill_runtime, workbench
from server import workflow_engine
from tests.test_human_writing_nodes import native_modules


def make_state():
    state_module, workflow = native_modules()
    state = workflow.new_article_state('测试')
    state.draft = '# 标题\n\n正文内容。'
    state.reader_simulation = [{'legacy': 'old draft'}]
    for name in ('intent', 'topic', 'research', 'strategy', 'draft'):
        state.nodes[name].status = 'passed'
    return state_module, workflow, state


@pytest.mark.parametrize('gate, fidelity, editorial', [
    ('needs_review', 'needs_review', 'local_review_completed'),
    ('unknown', 'needs_review', 'local_review_completed'),
    ('passed', 'needs_review', 'local_review_completed'),
    ('passed', 'passed', 'structure_needs_review'),
])
def test_pending_platform_review_never_becomes_passed(gate, fidelity, editorial):
    module, workflow, state = make_state()
    result = {'article': state.draft, 'review': {'gate': gate, 'article_sha256': skill_runtime.digest(state.draft),
              'fidelity_gate': {'status': fidelity}, 'editorial_quality': {'outcome': editorial}}}
    with TemporaryDirectory() as path, patch.object(adapter, '_skill_modules', return_value=(module, workflow)), \
         patch.object(workflow, '_quality_report', return_value={'blocked': False, 'findings': []}):
        payload = adapter.apply_node(state.to_dict(), 'review', result, Path(path))
        assert payload['nodes']['review']['status'] == 'needs_review'
        assert payload['reader_simulation'] == []
        assert payload['quality_report']['reader_simulation_status'] == 'skipped'
        assert payload['quality_report']['human_review_status'] == 'not_performed'
        assert not adapter.review_state(payload)['passed']


def test_restart_and_later_edit_do_not_inherit_passed_review():
    module, workflow, state = make_state()
    result = {'article': state.draft, 'review': {'gate': 'passed', 'article_sha256': skill_runtime.digest(state.draft),
              'fidelity_gate': {'status': 'passed'}}}
    with TemporaryDirectory() as path, patch.object(adapter, '_skill_modules', return_value=(module, workflow)), \
         patch.object(workflow, '_quality_report', return_value={'blocked': False, 'findings': []}):
        payload = adapter.apply_node(state.to_dict(), 'review', result, Path(path))
        assert adapter.review_state(payload)['passed']
        assert payload['quality_report']['editorial_quality']['status'] == 'not_assessed'
        assert payload['quality_report']['human_review_status'] == 'not_performed'
        payload['draft'] += ' 新增内容。'
        assert not adapter.review_state(payload)['passed']
        old = state.to_dict()
        old['nodes']['review']['status'] = 'passed'
        assert not adapter.review_state(old)['passed']  # old ambiguous states cannot be upgraded


def test_step_four_preserves_needs_review_without_scoring_or_auto_advance():
    article = '# 标题\n\n原稿。'
    session = {'id': 'p0', 'article': article, 'review': None, 'score': None,
               'framework': {'outline': ['一']}, 'enforce_skill_pipeline': True,
               'skill_execution': [], 'topic': '标题', 'status': '', 'current_step': 3}
    review = {'gate': 'needs_review', 'article_sha256': skill_runtime.digest(article)}
    with patch.object(workbench, '_review', return_value=(article, review)), \
         patch.object(workbench, '_score') as score, patch.object(workbench, '_session_view', side_effect=lambda s: dict(s)):
        result = workbench._advance(session, 4)
    assert result['review']['gate'] == result['status'] == 'needs_review'
    assert result['article'] == article
    score.assert_not_called()


def test_structural_problem_does_not_turn_fidelity_pass_into_overall_pass():
    article = '# 标题\n\n正文。'
    report = {'gate': 'passed', 'changed': False, 'article_sha256': skill_runtime.digest(article),
              'rounds': [{'diagnosis': {'fidelity_ok': True,
                          'structure_issue': {'status': 'needs_review', 'reason': '论述重复'}}}]}
    with patch.object(workbench, '_review_impl', return_value=(article, report)):
        result, final = workbench._review(article, {})
    assert result == article and final['gate'] == 'needs_review'
    assert final['fidelity_gate']['status'] == 'passed'
    assert final['editorial_quality']['outcome'] == 'structure_needs_review'
    assert '结构问题待处理' in final['summary']


def test_pending_editorial_issues_do_not_report_success_when_unchanged():
    article = '# 标题\n\n正文。'
    report = {'gate': 'passed', 'changed': False, 'article_sha256': skill_runtime.digest(article),
              'rounds': [], 'pending_review_notes': [{'reason': '重复问题尚未处理'}],
              'summary': '已复核，正文无需修改'}
    with patch.object(workbench, '_review_impl', return_value=(article, report)):
        result, final = workbench._review(article, {})
    assert result == article and final['gate'] == 'passed'
    assert final['fidelity_gate']['status'] == 'passed'
    assert final['editorial_quality']['status'] == 'needs_review'
    assert '正文未修改' in final['summary'] and '待处理' in final['summary']


def test_rephrased_numbers_are_allowed_but_meaning_change_is_rejected():
    original = '# 标题\n\n每周3次，先征得双方同意。'
    session = {'id': 'deep', 'brief': '深度重构'}
    with patch.object(workbench, '_text', return_value='# 标题\n\n一周安排四次，先征得双方同意。'), \
         patch.object(workbench, '_json_text', return_value={
             'topic_preserved': True, 'meaning_preserved': False, 'no_invention': False,
             'natural_voice': True, 'issues': ['频次从三次变成四次']}):
        with pytest.raises(workbench.ProviderError, match='主题或意思'):
            workbench._deep_structure_review(original, session)
    with patch.object(workbench, '_text', return_value='# 标题\n\n先征得双方同意，再一周安排三回。'), \
         patch.object(workbench, '_json_text', return_value={
             'topic_preserved': True, 'meaning_preserved': True, 'no_invention': True,
             'natural_voice': True, 'issues': []}):
        revised, report = workbench._deep_structure_review(original, session)
    assert '三回' in revised and report['gate'] == 'passed'


def test_deep_structure_requires_semantic_check_and_marks_human_review_pending():
    original = '# 标题\n\n先取得同意。\n\n再商量安排。'
    candidate = '# 标题\n\n商量安排前，先取得同意。'
    semantic = {'topic_preserved': True, 'meaning_preserved': True,
                'no_invention': True, 'natural_voice': True, 'issues': []}
    with patch.object(workbench, '_text', return_value=candidate), \
         patch.object(workbench, '_json_text', return_value=semantic) as reviewer:
        result, report = workbench._deep_structure_review(original, {'id': 'deep', 'brief': '深度重构'})
    assert result == candidate and report['gate'] == 'passed'
    assert report['fidelity_gate']['semantic_review'] == 'model_completed'
    assert report['editorial_quality']['status'] == 'needs_review'
    assert report['human_review_status'] == 'not_performed'
    reviewer.assert_called_once()


def test_deep_structure_repairs_a_meaning_drift_once():
    original = '# 标题\n\n每周三次，先征得同意。'
    drifted = '# 标题\n\n每周四次，先征得同意。'
    repaired = '# 标题\n\n先商量好，再每周安排三回。'
    failed = {'topic_preserved': True, 'meaning_preserved': False,
              'no_invention': False, 'natural_voice': True, 'issues': ['频次改变']}
    passed = {'topic_preserved': True, 'meaning_preserved': True,
              'no_invention': True, 'natural_voice': True, 'issues': []}
    with patch.object(workbench, '_text', side_effect=[drifted, repaired]) as writer, \
         patch.object(workbench, '_json_text', side_effect=[failed, passed]) as reviewer:
        result, report = workbench._deep_structure_review(original, {'id': 'deep', 'brief': '去 AI'})
    assert result == repaired and report['gate'] == 'passed'
    assert writer.call_count == reviewer.call_count == 2


def test_deep_structure_rejects_a_mid_sentence_cutoff():
    with patch.object(workbench, '_text', return_value='# 标题\n\n改到一半，'), \
         patch.object(workbench, '_json_text') as reviewer:
        with pytest.raises(workbench.ProviderError, match='句子中途截断'):
            workbench._deep_structure_review('# 标题\n\n完整原稿。', {'id': 'deep'})
    reviewer.assert_not_called()


@pytest.mark.parametrize('node', ['visual', 'delivery'])
def test_pending_review_is_not_resumed_into_downstream(node):
    module, workflow, state = make_state()
    state.nodes['review'].status = 'needs_review'
    state.quality_report = {'platform_review': {'gate': 'needs_review',
                            'article_sha256': skill_runtime.digest(state.draft)}}
    record = {'id': 'workflow', 'user_id': 'owner', 'mode': 'auto',
              'input': {}, 'state': {'article_state': state.to_dict()}}
    session = {'id': 'workflow', 'user_id': 'owner', 'article': state.draft, 'framework': {},
               'topic': '标题', 'review': {'gate': 'needs_review'}}
    with patch.object(adapter, '_skill_modules', return_value=(module, workflow)), \
         patch.object(workflow_engine.accounts, 'load_workbench_session', return_value=session), \
         patch.object(workflow_engine.workbench, 'step') as step:
        with pytest.raises(workbench.ProviderError, match='复核'):
            workflow_engine._execute_node(record, node)
    step.assert_not_called()
