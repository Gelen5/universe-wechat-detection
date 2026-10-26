import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


def test_rich_clipboard_roundtrip_preserves_chinese_styles_and_image(ui):
    page, _ = ui
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    page.goto('https://ui.test/')
    html = '<section style="color:#234532"><h1>中文标题：资料与行动</h1><p>中文、标点 &amp; emoji 🌍 都要完整。</p><p><strong>保留重点</strong></p><img alt="测试图片" src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jE8sAAAAASUVORK5CYII="></section>'
    page.evaluate('(html)=>PublisherCopy.copy({content_json:{article_html:html}})', html)
    data = page.evaluate('''async()=>{
      const [item]=await navigator.clipboard.read();
      return {html:await (await item.getType('text/html')).text(),plain:await (await item.getType('text/plain')).text()};
    }''')
    assert '中文标题：资料与行动' in data['html']
    assert 'data:image/png;base64,' in data['html']
    assert 'color:' in data['html']
    assert '中文、标点 & emoji 🌍 都要完整。' in data['plain']
    assert '<section' not in data['plain']
    page.evaluate("document.body.innerHTML='<div id=target contenteditable=true></div>'")
    page.locator('#target').focus()
    page.keyboard.press('Control+V')
    expect(page.locator('#target')).to_contain_text('中文、标点 & emoji 🌍 都要完整。')
    expect(page.locator('#target img')).to_have_count(1)


def test_copy_refuses_external_image_and_preview_excludes_controls(ui):
    page, _ = ui
    page.goto('https://ui.test/')
    result = page.evaluate('''()=>{
      try {PublisherCopy.fragment({content_json:{article_html:'<p>正文</p><img src="https://example.test/image.png">'}});}
      catch(error){return error.message;}
    }''')
    assert '图片尚未内嵌' in result
    preview = page.evaluate('''()=>PublisherCopy.preview({content:'<html><body><button>不复制按钮</button><main id="article-content"><p style="font-size:16px">完整正文</p></main></body></html>'})''')
    assert '完整正文' in preview
    assert '不复制按钮' not in preview


def test_rich_fallback_does_not_copy_html_source(ui):
    page, _ = ui
    page.context.grant_permissions(['clipboard-read', 'clipboard-write'])
    page.goto('https://ui.test/')
    page.evaluate("()=>{navigator.clipboard.write = async()=>{throw new Error('simulated API refusal')};}")
    page.evaluate("PublisherCopy.copy({content_json:{article_html:'<p style=\"color:#234532\">完整中文正文</p>'}})")
    data = page.evaluate("async()=>{const [item]=await navigator.clipboard.read();return {html:await (await item.getType('text/html')).text(),plain:await (await item.getType('text/plain')).text()}}")
    assert '完整中文正文' in data['plain']
    assert '<p' not in data['plain']
    assert 'color:' in data['html']
