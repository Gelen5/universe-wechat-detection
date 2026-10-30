import json
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from server import skill_host, workbench


def test_markdown_draft_is_wrapped_by_host_not_model():
    state = SimpleNamespace(user_request='写教程', selected_title='标题', topic='主题',
                            outline=[], writing_strategy={}, to_dict=lambda: {})
    article = '# 标题\n\n含有"引号"的正文。'
    with patch.object(workbench, 'provider_overrides', return_value=nullcontext()), \
         patch.object(skill_host, 'exemplar_prefix', return_value=''), \
         patch.object(skill_host, 'model_for', return_value=''), \
         patch.object(workbench, '_text', return_value=article) as generate:
        result = json.loads(skill_host._generate(state, 'draft')('旧 JSON 合同'))
    assert result['draft'] == article
    assert '只输出 Markdown' in generate.call_args.args[0]
    assert '旧 JSON 合同' not in generate.call_args.args[0]


def test_normal_layout_prepares_deterministic_plan():
    session = {'article': '完整正文。', 'theme': 'default', 'image_plan': {}}
    with patch.object(workbench, '_setting', side_effect=lambda name, default='': default), \
         patch.object(workbench, '_typeset_dsl', return_value='<p>完整正文。</p>') as render, \
         patch.object(workbench, '_text') as model:
        assert workbench._typeset(session) == '<p>完整正文。</p>'
    model.assert_not_called()
    render.assert_called_once_with(session)
    assert session['layout_plan_key']
