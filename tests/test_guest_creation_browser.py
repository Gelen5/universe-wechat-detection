"""Visitors can prepare work before signing in, without submitting paid jobs."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


@pytest.mark.parametrize('view,input_selector,button_selector,value', [
    ('wechat-plus', '#wp-input', '[data-wp-send]', '我想写一篇关于旅行的文章'),
    ('sticker-extract', '#sticker-url', '#sticker-start', 'https://mp.weixin.qq.com/s/example'),
    ('xhs-extract', '#xhs-extract-url', '#xhs-extract-start', 'https://www.xiaohongshu.com/explore/example'),
    ('douyin-extract', '#douyin-extract-url', '#douyin-extract-start', 'https://www.douyin.com/video/example'),
    ('article-visual', '#av-url', '#av-analyze', 'https://mp.weixin.qq.com/s/example'),
])
def test_guest_can_enter_input_and_action_opens_login(ui, view, input_selector, button_selector, value):
    page, state = ui
    page.route('**/api/auth/me', lambda route: route.fulfill(status=401, json={'detail': '请先登录'}))
    page.goto('http://ui.test/' + view, wait_until='networkidle')
    page.evaluate('(view) => setActiveView(view)', view)
    field = page.locator(input_selector)
    expect(field).to_be_enabled()
    field.fill(value)
    page.locator(button_selector).click()
    expect(page.locator('#auth-modal')).to_be_visible()
    expect(field).to_have_value(value)
    page.locator('#auth-close').click()
    expect(field).to_have_value(value)
    assert '/api/tasks' not in state['requests']


@pytest.mark.parametrize('view,selector,value', [
    ('wechat-plus', '#wp-input', '登录之前写的选题'),
    ('sticker-extract', '#sticker-url', 'https://mp.weixin.qq.com/s/example'),
    ('xhs-extract', '#xhs-extract-url', 'https://www.xiaohongshu.com/explore/example'),
])
def test_guest_input_survives_sign_in(ui, view, selector, value):
    page, _ = ui
    page.route('**/api/auth/me', lambda route: route.fulfill(status=401, json={'detail': '请先登录'}))
    page.route('**/api/wechat-plus/sessions', lambda route: route.fulfill(json={'sessions': []}))
    page.goto('http://ui.test/' + view, wait_until='networkidle')
    page.evaluate('(view) => setActiveView(view)', view)
    page.locator(selector).fill(value)
    page.evaluate("currentAccount = {id:'new-user', role:'user', display_name:'测试', email:'test@example.test'}; window.dispatchEvent(new Event('account-changed'))")
    expect(page.locator(selector)).to_have_value(value)
