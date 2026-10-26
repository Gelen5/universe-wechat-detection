"""Balances must survive sidebar decoration and asynchronous API updates."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

@pytest.mark.parametrize('width',[390,1440])
def test_wallet_survives_slow_account_load_and_later_updates(ui,width):
    page,_=ui
    page.set_viewport_size({'width':width,'height':900})
    pending=[]
    page.route('**/api/auth/me',lambda route:pending.append(route))
    page.goto('http://ui.test/workbench')
    expect(page.locator('.stat')).to_have_attribute('data-pd-wrapped','1')
    expect(page.locator('#wallet-balance')).to_have_text('—')
    assert pending
    pending[0].fulfill(json={'user':{'id':'u','display_name':'测试用户','email':'test@example.com','role':'user'},'wallet':{'balance':99679,'trial':0,'bonus':99679,'paid':0}})
    expect(page.locator('#wallet-balance')).to_have_text('99,679')
    page.evaluate("readApiResponse(new Response('{}',{headers:{'content-type':'application/json','X-Points-Balance':'99674'}}))")
    expect(page.locator('#wallet-balance')).to_have_text('99,674')
    page.evaluate("setWalletBalance('');setWalletBalance('invalid');setWalletBalance(null)")
    expect(page.locator('#wallet-balance')).to_have_text('99,674')
    page.locator('.app-tabs [data-view=home]').click()
    page.locator('.app-tabs [data-view=workbench]').click()
    expect(page.locator('#wallet-balance')).to_have_text('99,674')
    page.evaluate('setWalletBalance(0)')
    expect(page.locator('#wallet-balance')).to_have_text('0')
    expect(page.locator('#wallet-modal-balance')).to_have_text('0')

def test_unavailable_account_does_not_claim_zero_balance(ui):
    page,_=ui
    page.route('**/api/auth/me',lambda route:route.fulfill(status=503,json={'detail':'暂不可用'}))
    page.goto('http://ui.test/')
    expect(page.locator('.stat')).to_have_attribute('data-pd-wrapped','1')
    expect(page.locator('#wallet-balance')).to_have_text('—')
