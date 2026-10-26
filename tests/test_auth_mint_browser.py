"""Account surface layout and form behavior; no external requests."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

@pytest.mark.parametrize('width,height', [(1440,900),(390,844),(320,640),(390,440)])
def test_auth_layout_and_modes(ui, width, height):
    page, _ = ui
    page.set_viewport_size({'width':width,'height':height})
    page.route('**/api/auth/me', lambda r:r.fulfill(status=401,json={'detail':'请登录'}))
    page.goto('http://ui.test/workbench')
    modal=page.locator('#auth-modal')
    expect(modal).to_be_visible()
    expect(page.locator('#auth-title')).to_have_text('欢迎回来')
    card=page.locator('.auth-card').bounding_box()
    assert card['x'] >= 0 and card['x']+card['width'] <= width
    assert card['height'] <= height
    page.locator('[data-auth-mode=register]').click()
    expect(page.locator('#auth-display-name')).to_be_visible()
    expect(page.locator('#auth-password')).to_have_attribute('autocomplete','new-password')
    page.locator('#auth-password').fill('example-password')
    page.locator('#auth-password-toggle').click()
    expect(page.locator('#auth-password')).to_have_attribute('type','text')
    page.locator('#auth-password-toggle').click()
    expect(page.locator('#auth-password')).to_have_attribute('type','password')
    page.locator('[data-auth-mode=login]').click()
    expect(page.locator('#display-name-field')).to_be_hidden()
    page.route('**/api/auth/login',lambda r:r.fulfill(status=400,json={'detail':'邮箱或密码不正确'}))
    page.locator('#auth-email').fill('test@example.com')
    page.locator('#auth-submit').click()
    expect(page.locator('#auth-error')).to_contain_text('邮箱或密码不正确')
    page.locator('[data-auth-mode=register]').click()
    expect(page.locator('#auth-error')).to_be_hidden()
    page.locator('.auth-home').focus()
    page.keyboard.press('Shift+Tab')
    expect(page.locator('#auth-submit')).to_be_focused()
    if height > 650:
        page.locator('[data-auth-mode=login]').click()
        page.screenshot(path=f'D:/Download/auth-mint-{width}.png')

def test_auth_success_keeps_existing_api_contract(ui):
    page, _ = ui
    page.route('**/api/auth/me', lambda r:r.fulfill(status=401,json={'detail':'请登录'}))
    submitted=[]
    def login(route):
        submitted.append(route.request.post_data_json)
        route.fulfill(json={'user':{'id':'user','display_name':'测试用户','email':'test@example.com','role':'user'},'wallet':{'balance':100,'trial':100,'bonus':0,'paid':0}})
    page.route('**/api/auth/login',login)
    page.goto('http://ui.test/workbench')
    page.locator('#auth-email').fill('test@example.com')
    page.locator('#auth-password').fill('example-password')
    page.locator('#auth-submit').click()
    expect(page.locator('#auth-modal')).to_be_hidden()
    assert submitted == [{'email':'test@example.com','password':'example-password','display_name':''}]
    assert not page.locator('body').evaluate("el=>el.classList.contains('auth-open')")
