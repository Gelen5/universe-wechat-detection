"""Insufficient wallet points show a shared, non-payment contact dialog."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui, ROOT


@pytest.mark.parametrize('width',[390,1440])
def test_insufficient_points_submission_opens_contact_dialog_and_keeps_draft(ui,width):
    page,_=ui;page.set_viewport_size({'width':width,'height':900})
    def api(route):
        if route.request.method=='POST':
            route.fulfill(status=402,json={'detail':'积分不足：需要 30 积分，当前剩余 10 积分'})
        else: route.fallback()
    page.route('**/api/conversations/recent-1/messages',api)
    page.goto('http://ui.test/workbench?conversation=recent-1')
    # Desktop mint uses its normal composer; phone Folio bridges to that handler.
    page.locator('#workbench-topic' if width>1100 else '#folio-ask').fill('想写一篇实用的 AI 教程')
    page.locator('#start-workbench' if width>1100 else '#folio-send').click()
    dialog=page.get_by_role('dialog',name='积分不足')
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text('积分不足：需要 30 积分，当前剩余 10 积分')
    expect(dialog).to_contain_text('购买积分请联系🌍Gelen5')
    expect(page.locator('#workbench-topic')).to_have_value('想写一篇实用的 AI 教程')
    box=dialog.bounding_box()
    assert box['x']>=0 and box['x']+box['width']<=width
    page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>window.__contact=text}})")
    page.get_by_role('button',name='复制联系方式').click()
    expect(dialog).to_contain_text('已复制 Gelen5')
    assert page.evaluate('window.__contact')=='Gelen5'
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    assert not page.locator('body').evaluate('e=>e.classList.contains("points-notice-open")')


def test_shared_response_handler_ignores_other_errors_and_coalesces_dialogs(ui):
    page,_=ui;page.goto('http://ui.test/')
    page.evaluate("PointsNotice.fromResponse({status:402},{detail:'上游 API 额度不足'})")
    expect(page.locator('#points-notice')).to_have_count(0)
    page.evaluate("PointsNotice.fromResponse({status:500},{detail:'积分不足'})")
    expect(page.locator('#points-notice')).to_have_count(0)
    page.evaluate("readApiResponse(new Response(JSON.stringify({detail:'积分不足：需要 5 积分，当前剩余 0 积分'}),{status:402,headers:{'content-type':'application/json'}})).catch(()=>{})")
    expect(page.get_by_role('dialog',name='积分不足')).to_be_visible()
    page.evaluate("PointsNotice.open('积分不足：需要 8 积分，当前剩余 0 积分')")
    expect(page.locator('#points-notice')).to_have_count(1)
    expect(page.locator('#points-notice-detail')).to_contain_text('需要 8 积分')
    page.get_by_role('button',name='我知道了').click()
    expect(page.locator('#points-notice')).to_be_hidden()


def test_embedded_one_click_shows_parent_dialog(ui):
    page,_=ui;page.set_viewport_size({'width':1440,'height':1000})
    page.goto('http://ui.test/one-click-writing')
    frame=page.frame_locator('#one-click-writing-frame')
    expect(frame.locator('#q-topic')).to_be_attached()
    frame.locator('body').evaluate("()=>PointsNotice.fromResponse({status:402},{detail:'积分不足：需要 30 积分，当前剩余 0 积分'})")
    expect(page.get_by_role('dialog',name='积分不足')).to_be_visible()
    expect(frame.locator('#points-notice')).to_have_count(0)


def test_one_click_topic_request_uses_shared_notice(ui):
    page,_=ui;page.set_viewport_size({'width':1440,'height':1000})
    page.route('**/api/qihaoshou/topics',lambda route:route.fulfill(status=402,json={'detail':'积分不足：需要 3 积分，当前剩余 0 积分'}))
    page.goto('http://ui.test/qihaoshou')
    page.locator('#q-tab-ai').click()
    page.locator('#q-topics-refresh').click()
    expect(page.get_by_role('dialog',name='积分不足')).to_be_visible()
    expect(page.locator('#points-notice-detail')).to_contain_text('需要 3 积分')
