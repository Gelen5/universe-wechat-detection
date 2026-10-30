"""Synthetic Turnstile widget only; no real challenge or mail is submitted."""
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui  # noqa: F401


def test_registration_uses_fresh_turnstile_tokens_for_send_and_register(ui):
    page, _ = ui
    page.route('**/api/auth/me', lambda r:r.fulfill(status=401,json={'detail':'请登录'}))
    page.route('**/api/auth/config', lambda r:r.fulfill(json={
        'auth_engine':'better-auth','email_verification_required':True,'turnstile_site_key':'synthetic-test-key'}))
    page.route('https://challenges.cloudflare.com/turnstile/**', lambda r:r.fulfill(content_type='application/javascript',body='''
      window.turnstile={render:(host,options)=>{host.textContent='模拟人机验证';setTimeout(()=>options.callback('synthetic-'+options.action),0);return options.action;},remove:()=>{},reset:()=>{}};
      window.universeTurnstileReady();
    '''))
    sent=[]
    def send(route):
        sent.append(route.request.post_data_json)
        if route.request.url.endswith('/register'):
            route.fulfill(json={'user':{'id':'test','display_name':'测试','email':'new@example.test','role':'user'},'wallet':{'balance':6}})
        else:
            route.fulfill(json={'status':'success'})
    page.route('**/api/auth/email-code',send)
    page.route('**/api/auth/register',send)
    page.goto('http://ui.test/workbench')
    page.locator('[data-auth-mode=register]').click()
    expect(page.locator('#auth-challenge')).to_be_visible()
    page.locator('#auth-email').fill('new@example.test')
    page.locator('#auth-send-code').click()
    expect(page.locator('#auth-send-code')).to_have_text('已发送，60 秒后重试')
    assert sent[0]['turnstile_token']=='synthetic-register_email'
    page.locator('#auth-password').fill('Password12345')
    page.locator('#auth-email-code').fill('123456')
    page.locator('#auth-submit').click()
    expect(page.locator('#auth-modal')).to_be_hidden()
    assert sent[1]['turnstile_token']=='synthetic-register'
    assert sent[1]['email_code']=='123456'


def test_backup_link_loads_registration_without_exposing_otp_or_auto_creating_account(ui):
    page, state = ui
    page.route('**/api/auth/me', lambda r:r.fulfill(status=401,json={'detail':'请登录'}))
    page.route('**/api/auth/config', lambda r:r.fulfill(json={'auth_engine':'better-auth','email_verification_required':True}))
    page.route('**/api/auth/registration-link', lambda r:r.fulfill(json={'email':'link@example.test'}))
    page.goto('http://ui.test/#register='+'a'*64)
    expect(page.locator('#auth-title')).to_have_text('创建你的账号')
    expect(page.locator('#auth-email')).to_have_value('link@example.test')
    expect(page.locator('#auth-email-code-field')).to_be_hidden()
    expect(page.locator('#auth-password')).to_have_value('')
    assert page.evaluate('location.hash')==''
    assert '/api/auth/register' not in state['requests']
