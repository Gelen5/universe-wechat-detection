from unittest.mock import patch

import pytest

from server import workbench, writing_guidance
from server.draft_contract import contract_from, output_violations


@pytest.mark.parametrize('kind, requirements, expected', [
    ('emotional_opinion', '面向夫妻的情感观点', '情感观点'),
    ('opinion', 'AI 工具的个人观点', '观点'),
    ('tutorial', '公众号 Skill 操作教程', '教程'),
])
def test_v2_uses_genre_and_preserves_user_requirements(kind, requirements, expected):
    frame = {'name': '按材料推进', 'outline': ['开头', '展开'],
             'writing_strategy': {'article_type': kind, 'reader_question': '为什么',
                                  'available_materials': ['仅有用户素材']}, 'research': {}}
    prompts = []
    with patch.object(workbench, '_require_skill'), \
         patch.object(workbench.skill_runtime, 'node_rules', return_value=('DRAFT_RULES', [])), \
         patch.object(workbench.skill_runtime, 'context', side_effect=AssertionError('unneeded full context')), \
         patch.object(workbench.skill_runtime, 'length_issue', return_value=None), \
         patch.object(workbench, '_record_skill'), \
         patch.object(workbench, '_text', side_effect=lambda p, **kw: prompts.append(p) or '# 标题\n正文'):
        result = workbench._draft('主题', frame, '语气', requirements)
    assert result == '# 标题\n正文'
    assert expected in prompts[0] and requirements in prompts[0]
    assert '仅有用户素材' in prompts[0]
    assert '不把可能、建议写成必须或必然' in prompts[0]


def test_guide_and_opinion_remain_distinct():
    assert '教程' in writing_guidance.draft_strategy_v2({'article_type': 'tutorial'}, '婚姻沟通指南')
    assert '情感观点' in writing_guidance.draft_strategy_v2({'article_type': 'emotional_opinion'}, '')
    assert '用户要求沟通指南时以其要求为准' in writing_guidance.draft_strategy_v2({'article_type': 'emotional_opinion'}, '')


def test_contract_detects_unprovided_thought_but_preserves_evidenced_quote():
    contract = contract_from('900–1100字，不编造人物经历、对白和心理活动。', {'article_type': 'emotional_opinion'})
    assert contract.length == '900–1100字' and contract.forbid_dialogue and contract.forbid_psychology
    fake = '一方想说的是：“你一直没有听我说话。”'
    assert output_violations(fake, contract, '')
    assert not output_violations(fake, contract, fake)
    assert not output_violations('“旧账”不等于事情已经解决。', contract, '')


def test_unresolved_forbidden_thought_fails_without_overwriting():
    frame = {'name': '观点', 'outline': ['一', '二'], 'writing_strategy': {'article_type': 'opinion'}, 'research': {}}
    article = '# 标题\n\n一方想说的是：“你从来不听。”'
    with patch.object(workbench, '_require_skill'), \
         patch.object(workbench.skill_runtime, 'node_rules', return_value=('规则', [])), \
         patch.object(workbench.skill_runtime, 'length_issue', return_value=None), \
         patch.object(workbench, '_record_skill'), \
         patch.object(workbench, '_text', side_effect=[article, '{"edits":[]}']):
        with pytest.raises(workbench.ProviderError, match='一方想说'):
            workbench._draft('主题', frame, '语气', '不编造对白或心理活动')


def test_emotional_opinion_framework_does_not_require_steps():
    captured = []
    frame = {'name': '关系观点', 'outline': ['矛盾', '理解'],
             'writing_strategy': {'article_type': 'emotional_opinion'}}
    with patch.object(workbench, '_require_skill'), \
         patch.object(workbench.skill_runtime, 'context', return_value=('框架参考', [])), \
         patch.object(workbench.skill_runtime, 'node_rules', return_value=('策略', [])), \
         patch.object(workbench.workbench_research, 'search', return_value={}), \
         patch.object(workbench, '_record_skill'), \
         patch.object(workbench, '_json_text', side_effect=lambda p, **kw: captured.append(p) or frame):
        result = workbench._framework('夫妻', '观点', '情感观点文')
    assert result['writing_strategy']['article_type'] == 'emotional_opinion'
    assert '情感观点不是沟通教程或故事' in captured[0]


def test_default_length_is_guidance_and_never_costs_a_rewrite():
    frame = {'name': '观点', 'outline': ['一', '二'], 'writing_strategy': {'article_type': 'opinion'}, 'research': {}}
    short = '# 标题\n' + '文' * 400
    with patch.object(workbench, '_require_skill'), \
         patch.object(workbench.skill_runtime, 'node_rules', return_value=('规则', [])), \
         patch.object(workbench, '_record_skill'), \
         patch.object(workbench, '_text', side_effect=[short]) as writer:
        result = workbench._draft('主题', frame, '语气', '只填主题')
    assert result == short and writer.call_count == 1
    assert '1000–1200字' in writer.call_args_list[0].args[0]


def test_explicit_user_length_is_still_enforced_with_retry():
    frame = {'name': '观点', 'outline': ['一', '二'], 'writing_strategy': {'article_type': 'opinion'}, 'research': {}}
    short = '# 标题\n' + '文' * 400
    long_enough = '# 标题\n' + '文' * 900
    with patch.object(workbench, '_require_skill'), \
         patch.object(workbench.skill_runtime, 'node_rules', return_value=('规则', [])), \
         patch.object(workbench, '_record_skill'), \
         patch.object(workbench, '_text', side_effect=[short, long_enough]) as writer:
        result = workbench._draft('主题', frame, '语气', '800—1000字')
    assert result == long_enough and writer.call_count == 2


def test_user_length_does_not_get_default_range():
    frame = {'name': '观点', 'outline': ['一', '二'], 'writing_strategy': {'article_type': 'opinion'}, 'research': {}}
    with patch.object(workbench, '_require_skill'), \
         patch.object(workbench.skill_runtime, 'node_rules', return_value=('规则', [])), \
         patch.object(workbench, '_record_skill'), \
         patch.object(workbench, '_text', return_value='# 标题\n短文') as writer:
        workbench._draft('主题', frame, '语气', '正文约500字')
    assert '1000–1200字' not in writer.call_args.args[0]
