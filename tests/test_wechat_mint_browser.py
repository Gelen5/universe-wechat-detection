"""Desktop mint presentation must preserve the real workspace controls and routes."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


@pytest.mark.parametrize('width', [1101, 1280, 1440, 1920])
def test_desktop_mint_workspace_has_usable_chat_and_output(ui, width):
    page, state = ui
    page.set_viewport_size({'width':width,'height':1000})
    page.goto('http://ui.test/workbench')
    expect(page.locator('body')).to_have_class('atelier mint-wechat')
    expect(page.locator('#workbench-stage-nav button')).to_have_count(5)
    expect(page.locator('#workbench-topic')).to_be_visible()
    expect(page.locator('#folio-landing')).to_be_hidden()
    expect(page.locator('#workbench-chat-thread .from-ai')).to_be_visible()
    boxes = {s:page.locator(s).bounding_box() for s in ('.v3-topbar','#creation-assistant','#workbench-result','.composer-shell')}
    assert boxes['.v3-topbar']['x'] + boxes['.v3-topbar']['width'] < boxes['#creation-assistant']['x']
    assert boxes['#creation-assistant']['x'] + boxes['#creation-assistant']['width'] < boxes['#workbench-result']['x']
    assert boxes['.composer-shell']['y'] + boxes['.composer-shell']['height'] <= boxes['#creation-assistant']['y'] + boxes['#creation-assistant']['height']
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#workbench-topic').fill('只做桌面视觉验收，不调用模型')
    expect(page.locator('#workbench-topic')).to_have_value('只做桌面视觉验收，不调用模型')
    assert not [p for p in state['requests'] if p == '/api/runs']


def test_mint_is_removed_when_navigating_away_and_does_not_activate_on_mobile(ui):
    page, _ = ui
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto('http://ui.test/workbench')
    expect(page.locator('body')).to_have_class('atelier mint-wechat')
    page.locator('.app-tabs [data-view="home"]').click()
    expect(page.locator('body')).to_have_class('atelier')
    page.locator('.app-tabs [data-view="workbench"]').click()
    expect(page.locator('body')).to_have_class('atelier mint-wechat')
    page.set_viewport_size({'width':390,'height':844})
    expect(page.locator('body')).to_have_class('atelier')
    page.set_viewport_size({'width':1440,'height':1000})
    expect(page.locator('body')).to_have_class('atelier mint-wechat')


def test_existing_history_control_remains_operable(ui):
    page, _ = ui
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto('http://ui.test/workbench')
    page.locator('#recent-workbench-chats').click()
    expect(page.locator('#workbench-chat-history')).to_be_visible()
