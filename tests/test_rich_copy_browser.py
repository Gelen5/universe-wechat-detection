"""「复制排版」粘到公众号后台不能掉样式（端到端）。

公众号编辑器只保留行内 style：<style> 块和 class 会被整段丢掉。所以复制前
必须把样式压平，并且确认剪贴板里真的拿到了 text/html——只拿到纯文本时，
粘到公众号就是一篇没有排版的稿子。
"""
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

ROOT = Path(__file__).resolve().parents[1]

ARTICLE = (
    '<section style="font-family: -apple-system, sans-serif; font-size: 16px; line-height: 1.8; color: #333;">'
    '<h2 style="font-size: 1.4em; font-weight: bold; color: #1a73e8; margin: 1.3em 0 .7em;">'
    '<span leaf="">小标题</span></h2>'
    '<p style="margin: 1em 0; line-height: 1.8; color: #333; font-size: 16px;">'
    '<span leaf="">这是排版后的正文，粘贴到公众号后台必须还带着样式。</span></p>'
    "</section>"
)

SESSION = {
    "id": "s" * 32,
    "title": "排版会话",
    "version": 2,
    "state": {
        "messages": [{"role": "assistant", "content": "排版预览已生成"}],
        "article_state": {
            "draft": "# 标题\n\n这是排版后的正文。",
            "formatted_output": "/tmp/article.html",
            "quality_report": {},
            "evidence_pack": {},
        },
        "versions": [],
        "choices": [],
        "reply_options": [],
        "last_action": "format",
    },
    "turns": [],
    "updated_at": "2026-11-01T06:00:00Z",
}


def _clipboard(page):
    return page.evaluate('''async()=>{
      const [item]=await navigator.clipboard.read();
      const html=item.types.includes('text/html')?await (await item.getType('text/html')).text():'';
      const plain=item.types.includes('text/plain')?await (await item.getType('text/plain')).text():'';
      return {types:item.types,html,plain};
    }''')


def test_inline_styled_fragment_survives_as_rich_text(ui):
    page, _ = ui
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    page.goto('https://ui.test/')
    report = page.evaluate('''()=>PublisherCopy.copyHtml(
      '<section style="font-size:16px;line-height:1.8;color:#333">' +
      '<p style="margin:1em 0"><span leaf="">中文正文</span></p></section>')''')
    assert report['mode'] == 'clipboard'
    assert report['styleCount'] >= 2
    data = _clipboard(page)
    assert 'text/html' in data['types']
    assert 'font-size:16px' in data['html']
    assert '中文正文' in data['plain']
    assert '<p' not in data['plain']


def test_style_block_and_classes_are_flattened_before_copy(ui):
    """主题换成 <style> + class 以后，粘贴仍然要有样式。"""
    page, _ = ui
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    page.goto('https://ui.test/')
    report = page.evaluate('''()=>PublisherCopy.copyHtml(
      '<style>.t{color:#1a73e8;font-size:17px}.t p{margin:0 0 12px}</style>' +
      '<section class="t"><p class="lead">带主题的正文</p></section>')''')
    assert report['inlined'] is True
    html = _clipboard(page)['html']
    assert '<style' not in html, 'style 块没有被移除'
    assert 'class=' not in html, 'class 没有被移除'
    compact = html.replace(' ', '')
    assert 'color:#1a73e8' in compact
    assert 'font-size:17px' in compact


def test_custom_inline_style_wins_over_theme_rule(ui):
    page, _ = ui
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    page.goto('https://ui.test/')
    page.evaluate('''()=>PublisherCopy.copyHtml(
      '<style>p{color:#ff0000}</style><p style="color:#00ff00">作者自己定的颜色</p>')''')
    compact = _clipboard(page)['html'].replace(' ', '')
    assert 'color:#00ff00' in compact
    assert 'color:#ff0000' not in compact


def test_clipboard_api_refusal_falls_back_to_rich_selection(ui):
    page, _ = ui
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    page.goto('https://ui.test/')
    page.evaluate("()=>{navigator.clipboard.write=async()=>{throw new Error('simulated refusal')};}")
    report = page.evaluate('''()=>PublisherCopy.copyHtml('<p style="color:#234532">降级也要有样式</p>')''')
    assert report['mode'] == 'fallback'
    data = _clipboard(page)
    assert '降级也要有样式' in data['plain']
    assert '<p' not in data['plain']
    assert 'color:' in data['html']


def test_empty_fragment_is_refused_instead_of_copying_blank(ui):
    page, _ = ui
    page.goto('https://ui.test/')
    message = page.evaluate('''async()=>{try{await PublisherCopy.copyHtml('<style>p{color:red}</style>');return '';}catch(error){return error.message;}}''')
    assert '正文为空' in message


def test_wechat_plus_copy_button_puts_styles_on_the_clipboard(ui):
    """点「复制排版」之后，剪贴板里必须是一段带行内样式的 text/html。"""
    page, _ = ui
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])

    def handler(route):
        url = route.request.url
        if '/api/wechat-plus/' not in url:
            return route.fallback()
        if url.split('?')[0].endswith('/preview'):
            return route.fulfill(status=200, body=ARTICLE,
                                 headers={'content-type': 'text/html; charset=utf-8'})
        if '/sessions/' in url and route.request.method == 'PUT':
            return route.fulfill(json={'session': SESSION})
        if '/sessions/' in url:
            return route.fulfill(json={'session': SESSION})
        return route.fulfill(json={'sessions': [{**SESSION, 'state': {}}]})

    page.route('**/*', handler)
    page.goto('https://ui.test/wechat-plus')
    history = page.locator('[data-wp-history]')
    expect(history.locator(f'option[value="{SESSION["id"]}"]')).to_have_count(1, timeout=8000)
    history.select_option(SESSION["id"])
    button = page.locator('[data-wp-copy-html]')
    expect(button).to_be_enabled(timeout=8000)
    button.click()
    expect(page.locator('[data-wp-save-state]')).to_contain_text('排版已复制', timeout=8000)
    data = _clipboard(page)
    assert 'text/html' in data['types'], '剪贴板里没有富文本，粘到公众号只会剩文字'
    assert 'font-size: 1.4em' in data['html'] or 'font-size:1.4em' in data['html'].replace(' ', '')
    assert 'color: #1a73e8' in data['html'] or 'color:#1a73e8' in data['html'].replace(' ', '')
    assert '这是排版后的正文' in data['plain']
