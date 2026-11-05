from pathlib import Path
from urllib.parse import urlparse
import mimetypes
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser
from tests.test_auth_mint_browser import ui

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('width',[390,1440])
def test_agent_admin_page(browser,width):
    page=browser.new_page(viewport={'width':width,'height':900})
    errors=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    def serve(route):
        path=urlparse(route.request.url).path
        if path=='/api/admin/agents':
            route.fulfill(json={'agents':[{'user_id':'a','email':'agent@example.com','customers':2,'active':True}]})
        elif path=='/api/admin/agents/a/estimate':
            route.fulfill(json={'day':'2026-11-05','orders':1,'order_cents':1990,'refunded_cents':0,'estimate_cents':796})
        elif path=='/api/admin/agents/a/orders':
            route.fulfill(json={'orders':[{'email':'buyer@example.com','out_trade_no':'order1','total_amount':'20.00','refunded_amount':'2.00','status':'PARTIAL_REFUNDED','paid_at':'2026-11-05'}],'page':1,'total':1,'paid_customers':1,'order_total':'20.00','refunded_total':'2.00'})
        else:
            file=ROOT/'static'/('agent-admin.html' if path=='/admin/agents' else Path(path).name)
            route.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(str(file))[0] or 'text/plain')
    page.route('**/*',serve)
    page.goto('http://ui.test/admin/agents')
    expect(page.locator('#agents')).to_contain_text('agent@example.com')
    page.get_by_role('button',name='查看充值').click()
    expect(page.locator('#orders')).to_contain_text('buyer@example.com')
    expect(page.locator('#summary')).to_contain_text('累计退款 ¥2.00')
    page.locator('#settlement-day').fill('2026-11-05')
    page.get_by_role('button',name='计算',exact=True).click()
    expect(page.locator('#estimate-result')).to_contain_text('预估应结 ¥7.96')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert not errors
    page.close()

def test_agent_link_page(browser):
    page=browser.new_page(viewport={'width':390,'height':800})
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    def serve(route):
        path=urlparse(route.request.url).path
        if path=='/api/agent/me':
            route.fulfill(json={'code':'ABCDEF0123456789ABCDEF01','active':True})
        elif path=='/api/agent/orders':
            route.fulfill(json={'orders':[{'email':'b***@example.com','out_trade_no':'paid','total_amount':'19.90','refunded_amount':'0.00','status':'PAID','paid_at':'2026-11-05'}],'total':1,'paid_customers':1,'order_total':'19.90','refunded_total':'0.00'})
        else:
            file=ROOT/'static'/('agent.html' if path=='/agent' else Path(path).name)
            route.fulfill(body=file.read_bytes(),content_type=mimetypes.guess_type(str(file))[0] or 'text/plain')
    page.route('**/*',serve)
    page.goto('http://ui.test/agent')
    expect(page.locator('#link')).to_have_value('http://ui.test/?agent=ABCDEF0123456789ABCDEF01')
    expect(page.locator('#orders')).to_contain_text('b***@example.com')
    page.get_by_role('button',name='复制链接').click()
    expect(page.locator('#status')).not_to_be_empty()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert not errors
    page.close()

def test_promotion_link_survives_until_registration(ui):
    page,_=ui
    page.route('**/api/auth/me',lambda r:r.fulfill(status=401,json={'detail':'请登录'}))
    submitted=[]
    def register(route):
        submitted.append(route.request.post_data_json)
        route.fulfill(json={'user':{'id':'buyer','display_name':'客户','email':'buyer@example.com','role':'user'},'wallet':{'balance':0,'trial':0,'bonus':0,'paid':0},'agent_attribution':'bound'})
    page.route('**/api/auth/register',register)
    code='ABCDEF0123456789ABCDEF01'
    page.goto('http://ui.test/?agent='+code)
    page.locator('[data-auth-mode=register]').click()
    page.locator('#auth-email').fill('buyer@example.com')
    page.locator('#auth-password').fill('password123')
    page.locator('#auth-submit').click()
    expect(page.locator('#auth-modal')).to_be_hidden()
    assert submitted[0]['agent']==code
    assert page.evaluate("localStorage.getItem('universe.agent.code')") is None
