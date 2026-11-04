"""1B: the native Skill converter really runs and exposes its layout capability."""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from server import wechat_plus_layout as layout
from server import workbench
from tests import test_wechat_plus_service as plus_tests
from tests.test_wechat_plus_layout import DRAFT

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / 'vendor/skills/weChat-autoCreate'

# Long enough for the Skill's review gate, and structured so all five
# content-led module categories land on different blocks.
RICH_DRAFT = '''# 整理会议记录

会议结束后，整理会议记录可以先从待办入手。这里举一个假设场景：团队讨论了页面改版，却没有明确谁负责整理反馈。把原始讨论直接压成摘要，可能保留了话题，却丢掉后续行动。

> 有人说纪要就是复述，其实纪要要留下谁在什么时候答应了什么。

## 先区分讨论与决定

把记录分成已经确认的决定、尚未确定的问题和需要跟进的任务。有人说可以改按钮颜色，这只是建议；只有团队确认采用，才把它列为决定。缺少结论时写明待确认，不用猜测补齐。

- 已确认的决定，写清结论和确认人
- 尚未确定的问题，保留原话和分歧
- 需要跟进的任务，写到人和时间

## 再核对负责人

让工具输出原始发言、任务内容和负责人。找不到明确负责人，就保留空缺并在会后询问相关同事。整理的作用是暴露遗漏，不能把完整表格当成事实已经齐全。

## 最后回到原始材料

发出纪要前逐条核对讨论原文，删除没有依据的任务和承诺。涉及客户或公司敏感信息时，先按公司的资料处理要求选择工具，再决定是否上传。'''


@pytest.fixture(autouse=True)
def _skill(monkeypatch):
    monkeypatch.setattr(workbench, 'SKILL_DIR', PUBLISHER)


def _container_styles(html):
    soup = BeautifulSoup(html, 'html.parser')
    return [str(tag.get('style') or '') for tag in soup.find_all('div')
            if any(token in str(tag.get('style') or '')
                   for token in ('border-bottom:1px solid', 'border-left:', 'border-radius:10px',
                                 'border-top:1px solid'))]


def test_full_pipeline_runs_and_modules_are_visibly_distinct():
    theme = layout.choose('帮我选', None, fresh=True, content=RICH_DRAFT)
    html = layout.render(RICH_DRAFT, theme)
    assert 'plus-layout:' in html, 'pipeline silently fell back to the legacy template'
    styles = _container_styles(html)
    assert len(styles) >= 4
    assert len(set(styles)) >= 4, 'every module still looks like the same card'
    soup = BeautifulSoup(html, 'html.parser')
    assert '会议结束后' in soup.get_text()
    assert '有人说纪要就是复述' in soup.get_text()


def test_code_block_is_never_rewritten_by_the_full_pipeline():
    theme = layout.choose('帮我选', None, fresh=True, content=DRAFT)
    html = layout.render(DRAFT, theme)
    assert 'plus-layout:' in html, 'code blocks made the pipeline fall back'
    soup = BeautifulSoup(html, 'html.parser')
    assert '    print("a & b")' in soup.find('pre').get_text()
    assert soup.find('a')['href'] == 'https://example.com/guide?a=1&b=2'
    assert soup.find('img')['src'] == 'https://example.com/picture.png'


def test_h1_is_never_wrapped_inside_a_module_container():
    theme = layout.choose('帮我选', None, fresh=True, content=RICH_DRAFT)
    soup = BeautifulSoup(layout.render(RICH_DRAFT, theme), 'html.parser')
    heading = soup.find('h1')
    assert heading is not None
    assert heading.find_parent('div') is None


def test_module_library_and_style_keywords_are_exposed():
    assert layout.MODULE_COUNT == 29
    assert len(layout.STYLE_OPTIONS) == 4
    for name in layout.STYLE_OPTIONS:
        chosen = layout.choose(name)
        assert chosen['style_name'] == name
        assert chosen['style'] == layout.STYLE_KEYWORDS[name]
        assert chosen['modules'] and chosen['variant']
    first = layout.choose('帮我选', None, fresh=True, content=DRAFT)
    refined = layout.choose('标题居中，不要底色', first)
    assert refined['variant'] == first['variant']
    assert refined['style'] == first['style']
    assert [item['name'] for item in refined['modules']] == [item['name'] for item in first['modules']]
    assert refined['heading_align'] == 'center'


def test_bare_legacy_theme_still_uses_the_original_template():
    html = layout.render(DRAFT, dict(layout.THEMES['clean'], id='clean'))
    assert 'plus-layout:' not in html
    assert '<section' in html


def test_format_turn_exposes_the_capability_panel():
    case = plus_tests.NativeConversationTests(methodName='runTest')
    case.setUp()
    try:
        state = case.run_turn({}, '请排版下面的原稿：\n' + RICH_DRAFT, [
            {'action': 'format', 'existing_draft': RICH_DRAFT},
            {'reader_simulation': [{'role': '读者', 'feedback': '清晰'}],
             'revision_plan': []}])
        capability = state['layout_capability']
        assert capability['library_size'] == 29
        assert capability['module_count'] >= 1
        assert capability['style'] in layout.STYLE_OPTIONS
        assert len(capability['modules']) == capability['module_count']
        assert '墨金质感' in state['reply_options']
        assert '排版模块' in state['messages'][-1]['content']
        assert state['article_state']['draft'] == RICH_DRAFT
        preview = Path(state['article_state']['formatted_output']).read_text(encoding='utf-8')
        assert 'plus-layout:' in preview
    finally:
        case.tearDown()


def test_named_style_shortcut_forces_a_formatting_turn():
    case = plus_tests.NativeConversationTests(methodName='runTest')
    case.setUp()
    try:
        state = case.run_turn({}, '请排版下面的原稿：\n' + RICH_DRAFT, [
            {'action': 'format', 'existing_draft': RICH_DRAFT},
            {'reader_simulation': [{'role': '读者', 'feedback': '清晰'}],
             'revision_plan': []}])
        followup = case.run_turn(state, '深蓝金', [{'action': 'answer', 'reply': '好的'}])
        assert followup['last_action'] == 'format'
        assert followup['layout_theme']['style'] == 'navy_gold'
        assert followup['layout_theme']['style_name'] == '深蓝金'
        assert followup['article_state']['draft'] == RICH_DRAFT
    finally:
        case.tearDown()
