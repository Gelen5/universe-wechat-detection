"""Deterministic anti-AI execution layer for 公众号创作 Plus.

These tests use the vendored Skill detectors for real; they are read-only
subprocess calls and never modify Skill source.
"""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest

from server import wechat_plus_humanizer as humanizer
from server import wechat_plus_service as service
from server import workbench
from tests import test_wechat_plus_service as plus_tests

ROOT = Path(__file__).resolve().parents[1]
ANTI_AI = ROOT / 'vendor/skills/universe-delete-ai-skill'
PUBLISHER = ROOT / 'vendor/skills/weChat-autoCreate'

AI_DRAFT = '''# 如何提升睡眠质量：一份系统性的实践指南

值得注意的是，睡眠不仅仅是休息，更是身体修复的关键环节。首先，我们需要建立规律的作息；其次，要优化睡眠环境；最后，应当关注饮食与运动。

综上所述，良好的睡眠是健康生活的重要基石。通过多维度的系统性优化，我们可以有效赋能自身的睡眠质量，形成正向闭环。

从这个维度来看，睡眠质量的提升并非一蹴而就，而是一个持续迭代的过程。总而言之，坚持科学的方法至关重要。

- 第一，保持固定作息时间
- 第二，控制睡前屏幕使用
- 第三，营造舒适的睡眠环境

值得注意的是，每个人的情况都不尽相同，因此需要根据自身实际进行动态调整。'''

HUMAN_DRAFT = '''# 如何提升睡眠质量：一份系统性的实践指南

老周上夜班那阵子，回家躺下已经快三点了。人累得不行，眼睛却睁着，天花板那道裂纹他能数出几道弯。他媳妇把客厅那盏灯关了，说了句"别刷手机了"，他嗯了一声，手还是没放下。

后来他改了一件事，闹钟定在十一点半，响了就把手机扣过去放到玄关。头三天难受，第四天开始能睡整觉。他跟我说，最难的不是早睡，是承认自己其实舍不得那半小时没人找的时间。

睡不好的人多半不是不懂道理。屋里太亮、枕头太高、睡前那杯茶，这些都能试，但得一样一样试，才知道卡在哪儿。老周试到第二周才发现是窗帘太薄，早上五点光就进来了。

我自己也有过一段，稿子压着，躺下脑子里还在改句子。后来干脆把没写完的那句抄到纸上，写完再睡，比反复告诉自己"别想了"管用。

你要是真想调，今晚先挑一件最小的，别一次改三样。改完没用就换，别跟自己较劲。'''


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.setattr(workbench, 'ANTI_AI_SKILL_DIR', ANTI_AI)
    monkeypatch.setattr(workbench, 'SKILL_DIR', PUBLISHER)
    for name in (humanizer.ENABLED_ENV, humanizer.ROUNDS_ENV,
                 humanizer.FICTION_ENV, humanizer.SIMILARITY_ENV):
        monkeypatch.delenv(name, raising=False)


def test_verified_rewrite_is_applied_with_real_skill_detectors():
    text, report = humanizer.humanize(AI_DRAFT, lambda _: {'draft': HUMAN_DRAFT},
                                      context={'topic': '睡眠'})
    assert report['status'] == 'passed'
    assert report['rounds'] == 1
    assert text == HUMAN_DRAFT.strip()
    assert report['gates']['similarity'] < 0.30
    assert report['before']['forbidden'] > report['after']['forbidden']
    assert report['after']['forbidden'] == 0
    assert report['after']['signals'] <= report['before']['signals']
    assert report['gates']['protected_spans_ok'] is True


def test_surface_rewrite_is_rolled_back_instead_of_delivered():
    text, report = humanizer.humanize(AI_DRAFT, lambda _: {'draft': AI_DRAFT})
    assert text == AI_DRAFT
    assert report['status'] == 'rolled_back'
    assert report['rounds'] >= 1
    assert all(not attempt['passed'] for attempt in report['attempts'])
    assert any(not attempt['similarity_ok'] for attempt in report['attempts'])


def test_model_or_detector_failure_never_costs_the_draft():
    def offline(_):
        raise RuntimeError('relay unavailable')
    text, report = humanizer.humanize(AI_DRAFT, offline)
    assert text == AI_DRAFT
    assert report['reason'] == 'rewrite_unavailable'

    def malformed(_):
        return {'reply': '没有正文'}
    text2, report2 = humanizer.humanize(AI_DRAFT, malformed)
    assert text2 == AI_DRAFT


def test_switch_short_draft_and_similarity_bound(monkeypatch):
    calls = []
    monkeypatch.setenv(humanizer.ENABLED_ENV, '0')
    text, report = humanizer.humanize(AI_DRAFT, lambda p: calls.append(p) or {'draft': HUMAN_DRAFT})
    assert text == AI_DRAFT and not calls and report['status'] == 'skipped'
    monkeypatch.delenv(humanizer.ENABLED_ENV)

    short = '# 短稿\n\n内容。'
    assert humanizer.humanize(short, lambda _: {'draft': HUMAN_DRAFT})[0] == short

    monkeypatch.setenv(humanizer.SIMILARITY_ENV, '0.10')
    _, strict = humanizer.humanize(AI_DRAFT, lambda _: {'draft': HUMAN_DRAFT})
    assert strict['status'] in {'passed', 'rolled_back'}
    # 0.50 is the deliberate floor: an over-tight threshold would reject
    # legitimate rewrites and waste model rounds.
    assert humanizer.max_similarity() == 0.50


def test_protected_facts_and_title_block_an_unverified_rewrite():
    with_facts = AI_DRAFT + '\n\n参考 https://example.com/sleep 的说明，样本 1200 人，持续 8 周。'
    text, report = humanizer.humanize(with_facts, lambda _: {'draft': HUMAN_DRAFT})
    assert text == with_facts
    assert report['status'] == 'rolled_back'
    assert any(attempt['missing_protected_spans'] for attempt in report['attempts'])


def test_fiction_switch_is_written_into_the_prompt(monkeypatch):
    monkeypatch.setenv(humanizer.ROUNDS_ENV, '1')
    prompts = []

    def capture(prompt):
        prompts.append(prompt)
        return {'draft': AI_DRAFT}

    humanizer.humanize(AI_DRAFT, capture)
    assert '已明确授权虚构' in prompts[0]
    assert '不得新增统计数字' in prompts[0]

    prompts.clear()
    monkeypatch.setenv(humanizer.FICTION_ENV, '0')
    humanizer.humanize(AI_DRAFT, capture)
    assert '不要补写人物、对话、场景或细节' in prompts[0]
    assert '已明确授权虚构' not in prompts[0]


def test_scrub_keeps_h1_punctuation_and_removes_mechanical_rhythm():
    source = '# 标题：留着\n\n值得注意的是，这里——有破折号。综上所述，还是别改标题。'
    result = humanizer.scrub(source)
    assert result.startswith('# 标题：留着')
    assert '——' not in result
    assert '值得注意的是' not in result and '综上所述' not in result
    assert '这里' in result


def test_cancellation_escapes_the_fail_safe_handlers():
    class Cancelled(RuntimeError):
        pass

    def cancelled():
        raise Cancelled('stop')

    with pytest.raises(Cancelled):
        humanizer.humanize(AI_DRAFT, lambda _: {'draft': HUMAN_DRAFT},
                           check_cancelled=cancelled, passthrough=(Cancelled,))

    def cancelled_generate(_):
        raise Cancelled('stop')
    with pytest.raises(Cancelled):
        humanizer.humanize(AI_DRAFT, cancelled_generate, passthrough=(Cancelled,))

    # Without the passthrough contract, the same signal is absorbed.
    text, report = humanizer.humanize(AI_DRAFT, cancelled_generate)
    assert text == AI_DRAFT


def test_write_turn_applies_the_verified_human_voice():
    case = plus_tests.NativeConversationTests(methodName='runTest')
    case.setUp()
    try:
        article = service.runtime.initialize('写一篇关于睡眠的文章')
        for node in article['nodes']:
            article['nodes'][node]['status'] = 'passed'
        article['draft'] = AI_DRAFT
        article['selected_title'] = '睡眠'
        initial = {'article_state': article, 'selected_topic': {'title': '睡眠'},
                   'preferences': {}}

        def fulfill(payload, node, generate, **kwargs):
            value = deepcopy(payload)
            value['nodes'][node]['status'] = 'passed'
            if node == 'draft':
                value['draft'] = AI_DRAFT
            return value

        with patch.object(service.runtime, 'fulfill', side_effect=fulfill), \
             patch.object(service.humanizer, 'humanize',
                          return_value=(HUMAN_DRAFT, {'summary': '活人感重写完成'})) as human:
            state = case.run_turn(initial, '直接写', [{'action': 'write'}])
        human.assert_called_once()
        assert human.call_args.kwargs['passthrough'] == (service.Cancelled,)
        assert state['article_state']['draft'] == HUMAN_DRAFT
        assert state['humanizer_report']['summary'] == '活人感重写完成'
        assert '活人感重写完成' in state['messages'][-1]['content']
        assert state['versions'][-1]['draft'] == AI_DRAFT  # model draft kept in history
    finally:
        case.tearDown()


def test_formatting_turn_never_invokes_the_humanizer():
    case = plus_tests.NativeConversationTests(methodName='runTest')
    case.setUp()
    try:
        with patch.object(service.humanizer, 'humanize') as human:
            state = case.run_turn({}, '请排版下面的原稿：\n' + AI_DRAFT, [
                {'action': 'format', 'existing_draft': AI_DRAFT},
                {'reader_simulation': [{'role': '读者', 'feedback': '清晰'}],
                 'revision_plan': []},
                {'first_screen': '标题与首段', 'components': ['callout'],
                 'decoration_budget': 3, 'emphasis': '',
                 'image_evidence': '', 'line_break_risks': ''}])
        human.assert_not_called()
        assert state['article_state']['draft'] == AI_DRAFT
    finally:
        case.tearDown()
