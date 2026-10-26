"""Public market results must not depend on auxiliary request availability."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

@pytest.mark.parametrize('spa',[False,True])
def test_market_list_loads_while_auxiliary_requests_are_pending(ui,spa):
    page,_=ui
    pending=[]
    page.route('**/api/auth/me',lambda route:pending.append(route))
    page.route('**/api/market/meta',lambda route:pending.append(route))
    page.route('**/api/market/skills?featured=true',lambda route:pending.append(route))
    page.goto('http://ui.test/' if spa else 'http://ui.test/market')
    if spa: page.locator('.app-tabs [data-view=market]').click()
    expect(page.locator('#market-list')).to_contain_text('没有匹配的 skill')
    assert len(pending)>=3
    for route in pending: route.fulfill(status=503,json={'detail':'模拟辅助服务不可用'})

def test_market_failed_initial_request_retries_on_reentry(ui):
    page,state=ui
    state['fail_market']=True
    page.goto('http://ui.test/')
    page.locator('.app-tabs [data-view=market]').click()
    expect(page.locator('[data-market-retry]')).to_be_visible()
    state['fail_market']=False
    page.locator('.app-tabs [data-view=home]').click()
    page.locator('.app-tabs [data-view=market]').click()
    expect(page.locator('#market-list')).to_contain_text('没有匹配的 skill')
