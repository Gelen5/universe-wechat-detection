"""Phone home and real restored writing states; all APIs intercepted."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui
from tests.test_workbench_card_browser import _artifact


@pytest.mark.parametrize('width,height', [(360,740),(390,844),(430,932),(768,1024)])
def test_mobile_home_and_landing_keep_brand_and_input_visible(ui,width,height):
    page,_=ui;page.set_viewport_size({'width':width,'height':height})
    page.goto('http://ui.test/')
    expect(page.locator('#home .mobile-site-brand')).to_be_visible()
    expect(page.locator('.universe-start')).to_be_in_viewport()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.goto('http://ui.test/workbench')
    expect(page.locator('.fl-mobile-copy').first).to_be_visible()
    expect(page.locator('#folio-send')).to_be_in_viewport()
    assert float(page.locator('#folio-ask').evaluate('e=>parseFloat(getComputedStyle(e).fontSize)'))>=16
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width,height', [(360,740),(390,844),(430,932)])
def test_mobile_restored_chat_has_reachable_composer_and_work_view(ui,width,height):
    page,_=ui;page.set_viewport_size({'width':width,'height':height})
    artifact=_artifact('article','这是一篇用于验证手机阅读布局的文章。\n\n内容会保留在当前对话中。',1)
    def artifacts(route): route.fulfill(json={'artifacts':[artifact]})
    def messages(route): route.fulfill(json={'messages':[{'role':'user','content':'写一篇 AI 工具实测','content_json':{}},{'role':'assistant','content':'正文已完成，可以查看作品。','content_json':{}}]})
    page.route('**/api/conversations/recent-1/artifacts*',artifacts)
    page.route('**/api/conversations/recent-1/messages',messages)
    page.goto('http://ui.test/workbench?conversation=recent-1')
    expect(page.locator('#workbench-topic')).to_be_visible()
    expect(page.locator('#workbench-action-card')).to_be_visible()
    expect(page.locator('#start-workbench')).to_be_in_viewport()
    composer=page.locator('.composer-shell').bounding_box()
    nav=page.locator('.v3-topbar').bounding_box()
    assert composer['y']+composer['height']<=height-70
    assert page.locator('#creation-assistant').bounding_box()['width']>=width-40
    expect(page.locator('#recent-workbench-chats')).to_be_visible()
    page.locator('#workbench-view-toggle').click()
    expect(page.locator('#workbench-result')).to_be_visible()
    expect(page.locator('#creation-assistant')).to_be_hidden()
    page.locator('[data-workbench-stage="writing"]').click()
    expect(page.locator('#result-title')).to_have_text('测试作品')
    page.locator('#workbench-view-toggle').click()
    expect(page.locator('#workbench-topic')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    # Simulate the visual viewport shrinking as a phone software keyboard opens.
    page.locator('#workbench-topic').focus()
    page.evaluate("Object.defineProperty(visualViewport,'height',{configurable:true,value:420});visualViewport.dispatchEvent(new Event('resize'))")
    expect(page.locator('body')).to_have_class('atelier mobile-writing-keyboard')
    expect(page.locator('.v3-topbar')).to_be_hidden()
    composer=page.locator('.composer-shell').bounding_box()
    assert composer['y']+composer['height']<=420
    page.evaluate("delete visualViewport.height;visualViewport.dispatchEvent(new Event('resize'))")
    expect(page.locator('.v3-topbar')).to_be_visible()
