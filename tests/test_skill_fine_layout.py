from pathlib import Path
import base64
import io
import pytest
from PIL import Image
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


def test_skill_gate_failure_is_repaired_and_all_checks_run_again(tmp_path):
    bad = HTML.replace('line-height:1.85', 'line-height:9')
    calls = []
    def generate(prompt):
        calls.append(prompt)
        return bad if len(calls) == 1 else HTML
    events = []
    session = {'_layout_progress': lambda step, data: events.append(data['label'])}
    result = render(session, skill_root=ROOT, output_dir=tmp_path,
                    source_markdown='# 把资料整理成可用的结果\n\n先核实来源，再把未确认的内容单独标出。',
                    instructions='Skill组件规范', generate=generate)
    assert len(calls) == 2
    assert 'line_height_out_of_range' in calls[1]
    assert session['layout_repair_trace'][0]['status'] == 'rejected'
    assert session['layout_repair_trace'][1]['status'] == 'passed'
    assert any('修复' in label for label in events)
    assert 'line-height:9' not in result


def test_unsafe_styles_are_repaired_without_second_model_request(tmp_path):
    bad = HTML.replace('padding:12px', 'padding:12px;position:relative;box-shadow:0 1px 2px #000')
    bad = bad.replace('<section ', '<section class="decoration" id="candidate" ', 1)
    calls = []
    def generate(prompt):
        calls.append(prompt)
        return bad
    session = {}
    result = render(session, skill_root=ROOT, output_dir=tmp_path,
                    source_markdown='# 把资料整理成可用的结果\n\n先核实来源，再把未确认的内容单独标出。',
                    instructions='Skill组件规范', generate=generate)
    assert len(calls) == 1
    assert 'position:' not in result and 'box-shadow:' not in result
    assert 'class=' not in result and 'id=' not in result
    assert 'removed_nonportable_styles' in session['layout_repair_trace'][0]['local_repairs']


def test_incomplete_text_cannot_pass_even_after_model_retry(tmp_path):
    calls = []
    def generate(prompt):
        calls.append(prompt)
        return HTML.replace('先核实来源，再把未确认的内容单独标出。', '正文被截断。')
    with pytest.raises(ValueError, match='自动修复后仍未通过'):
        render({}, skill_root=ROOT, output_dir=tmp_path,
               source_markdown='# 把资料整理成可用的结果\n\n先核实来源，再把未确认的内容单独标出。',
               instructions='Skill组件规范', generate=generate)
    assert len(calls) == 2


def test_image_and_unicode_survive_repairs_and_skill_checks(tmp_path):
    buffer = io.BytesIO()
    Image.new('RGB', (2, 2), 'white').save(buffer, format='PNG')
    image_uri = 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()
    source = '# 把资料整理成可用的结果\n\n先核实来源，再把未确认的内容单独标出。\n\n![配图](' + image_uri + ')'
    prompts = []
    def generate(prompt):
        prompts.append(prompt)
        return HTML + '<img src="PUBLISHER_ASSET_1" alt="配图" style="width:100%">'
    session = {}
    result = render(session, skill_root=ROOT, output_dir=tmp_path, source_markdown=source,
                    instructions='Skill组件规范', generate=generate)
    assert len(prompts) == 1
    assert image_uri in result
    assert 'max-width:100%' in result
    assert 'prevented_image_upscaling' in session['layout_repair_trace'][0]['local_repairs']


def test_broken_source_image_fails_before_any_model_request(tmp_path):
    calls = []
    with pytest.raises(ValueError, match='复制版图片'):
        render({}, skill_root=ROOT, output_dir=tmp_path,
               source_markdown='正文\n\n![broken](data:image/png;base64,aGVsbG8=)',
               instructions='', generate=lambda prompt: calls.append(prompt))
    assert calls == []


def test_fidelity_preserves_english_word_spacing_across_inline_elements():
    source = '<p>AI tools make work easier.</p>'
    assert validate_fragment('<section>\n<p><span>AI</span> <strong>tools</strong> make work easier.</p>\n</section>', source)
    with pytest.raises(ValueError, match='文字不一致'):
        validate_fragment('<p>AItools make work easier.</p>', source)


def test_markdown_code_final_newline_does_not_become_a_prose_space():
    source = '<p>前文</p><pre><code>if ready:\n    run()\n</code></pre><p>后文</p>'
    rendered = '<p>前文</p><pre><code>if ready:\n    run()</code></pre><p>后文</p>'
    assert validate_fragment(rendered, source)


def test_first_level_two_heading_is_not_dropped_from_original():
    from server.workbench import _build_article_markdown
    session = {'id': 'test', 'topic': '完整文章', 'theme': 'default',
               'article': '## 第一个章节\n\n完整正文。', 'images': [], 'image_plan': {}}
    source = _build_article_markdown(session, fine_layout=True)
    assert '## 第一个章节' in source
    assert '完整正文。' in source
