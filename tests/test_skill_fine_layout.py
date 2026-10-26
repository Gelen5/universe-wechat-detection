from pathlib import Path
import pytest
from server.skill_fine_layout import render, validate_fragment, code_wrap_allowance

ROOT = Path(__file__).resolve().parents[1] / 'vendor/skills/weChat-autoCreate'
SOURCE = '<h1>把资料整理成可用的结果</h1><p>先核实来源，再把未确认的内容单独标出。</p>'
HTML = '<section style="padding:12px;background:#ffffff;color:#242424"><h1 style="font-size:24px;line-height:1.5;margin:0 0 24px">把资料整理成可用的结果</h1><p style="font-size:16px;line-height:1.85;margin:16px 0">先核实来源，再把未确认的内容单独标出。</p></section>'


def test_mode_a_uses_skill_template_and_different_design_briefs(tmp_path):
    prompts = []
    def generate(prompt):
        prompts.append(prompt)
        return HTML if len(prompts) == 1 else HTML.replace('padding:12px', 'padding:20px')
    session = {'brief': '极简排版', 'theme': 'default'}
    args = dict(skill_root=ROOT, source_markdown='# 把资料整理成可用的结果\n\n先核实来源，再把未确认的内容单独标出。', instructions='Skill组件规范', generate=generate)
    render(session, output_dir=tmp_path / 'one', **args)
    assert session['typeset_style'] == 'A-components'
    assert '<!-- ========== ARTICLE HTML START ========== -->' in session['preview_document']
    assert '从零搭建微信公众号自动化排版系统' not in session['preview_document']
    second = {'brief': '再次排版', 'previous_layout': session['typeset_html'], 'previous_layout_hash': session['layout_html_hash']}
    render(second, output_dir=tmp_path / 'two', **args)
    assert second['layout_html_hash'] != session['layout_html_hash']
    assert prompts[0] != prompts[1]


@pytest.mark.parametrize('bad', [
    HTML.replace('先核实来源，再把未确认的内容单独标出。', '被改写的内容。'),
    HTML + '<script></script>',
    HTML.replace('padding:12px', 'position:fixed'),
    HTML + '<img src="https://example.test/test.png">',
])
def test_missing_text_and_unportable_content_blocked(bad):
    with pytest.raises(ValueError):
        validate_fragment(bad, SOURCE)


def test_intact_code_pre_wrap_uses_skill_documented_allowance(tmp_path):
    code = '<pre style="white-space:pre-wrap;font-size:14px;line-height:1.8"><code>if ready:\n    run()</code></pre>'
    session = {}
    render(session, skill_root=ROOT, output_dir=tmp_path,
           source_markdown='# 把资料整理成可用的结果\n\n先核实来源，再把未确认的内容单独标出。\n\n```python\nif ready:\n    run()\n```',
           instructions='Skill组件规范', generate=lambda prompt: HTML + code)
    assert 'css_white_space_pre' in session['compliance_check']['waived']
    assert 'css_white_space_pre' in session['compliance_allowances']


def test_code_wrap_allowance_does_not_cover_prose_or_changed_indentation():
    source = '<pre><code>if ready:\n    run()</code></pre>'
    assert not code_wrap_allowance('<p style="white-space:pre-wrap">正文</p>' + source, source)
    assert not code_wrap_allowance('<pre style="white-space:pre-wrap"><code>if ready:\nrun()</code></pre>', source)
    with pytest.raises(ValueError, match='代码块'):
        validate_fragment('<pre><code>if ready:\nrun()</code></pre>', source)
