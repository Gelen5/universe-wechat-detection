import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

@pytest.mark.parametrize('width,height',[(390,844),(320,640)])
def test_registration_optional_fields_and_validation(ui,width,height):
 page,_=ui; page.set_viewport_size({'width':width,'height':height})
 page.route('**/api/auth/me',lambda r:r.fulfill(status=401,json={'detail':'请登录'}))
 page.route('**/api/auth/config',lambda r:r.fulfill(json={'email_verification_required':True}))
 page.route('**/api/auth/email-code',lambda r:r.fulfill(json={'status':'success'}))
 page.goto('http://ui.test/workbench')
 page.locator('[data-auth-mode=register]').click()
 expect(page.locator('#auth-description')).to_contain_text('贴图复刻')
 expect(page.locator('#auth-display-name')).to_be_hidden()
 page.locator('#auth-send-code').click()
 expect(page.locator('#auth-error')).to_contain_text('输入邮箱')
 page.locator('#auth-email').fill('bad-email')
 page.locator('#auth-send-code').click()
 expect(page.locator('#auth-error')).to_contain_text('邮箱格式')
 page.locator('#auth-email').fill('test@example.com')
 page.locator('#auth-send-code').click()
 expect(page.locator('#auth-code-status')).to_contain_text('test@example.com')
 expect(page.locator('#auth-send-code')).to_be_disabled()
 page.locator('#auth-password').fill('12345678')
 page.locator('#auth-submit').click()
 expect(page.locator('#auth-error')).to_contain_text('6 位验证码')
 page.locator('#auth-optional summary').click()
 expect(page.locator('#auth-display-name')).to_be_visible()
 expect(page.locator('#auth-invite-code')).to_be_visible()
 assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')

def test_invitation_opens_optional_fields(ui):
 page,_=ui
 page.route('**/api/auth/me',lambda r:r.fulfill(status=401,json={'detail':'请登录'}))
 page.goto('http://ui.test/workbench?ref=ABC123')
 expect(page.locator('#auth-invite-code')).to_have_value('ABC123')
 expect(page.locator('#auth-optional')).to_have_attribute('open','')

def test_register_error_keeps_fields_and_selected_invite(ui):
 page,_=ui
 page.route('**/api/auth/me',lambda r:r.fulfill(status=401,json={'detail':'请登录'}))
 page.route('**/api/auth/config',lambda r:r.fulfill(json={'email_verification_required':False}))
 page.route('**/api/auth/register',lambda r:r.fulfill(status=400,json={'detail':'注册暂不可用，请稍后重试'}))
 page.goto('http://ui.test/workbench?ref=ABC123')
 page.locator('[data-auth-mode=register]').click()
 page.locator('#auth-email').fill('test@example.com')
 page.locator('#auth-password').fill('example-password')
 page.locator('#auth-display-name').fill('昵称')
 page.locator('#auth-submit').click()
 expect(page.locator('#auth-error')).to_contain_text('注册暂不可用')
 expect(page.locator('#auth-email')).to_have_value('test@example.com')
 expect(page.locator('#auth-password')).to_have_value('example-password')
 expect(page.locator('#auth-invite-code')).to_have_value('ABC123')
 expect(page.locator('#auth-display-name')).to_have_value('昵称')
