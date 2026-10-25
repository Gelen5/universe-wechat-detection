"""One desktop navigation across the SPA and standalone resource pages."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


@pytest.mark.parametrize('width', [1101, 1440, 2560])
def test_sidebar_stays_identical_across_all_main_tabs(ui, width):
    page, _ = ui
    page.set_viewport_size({'width':width,'height':1159})
    page.goto('http://ui.test/workbench')
    def style():
        return page.locator('.v3-topbar').evaluate("e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return [r.x,r.y,r.width,r.height,s.padding,s.backgroundColor,s.borderRadius,getComputedStyle(e.querySelector('.app-tabs a > span')).fontSize]}")
    baseline = style()
    for view in ['home','one-click-writing','xiaohongshu','tie-tu','morning','diagnose','hit-detector','workbench']:
        page.locator('.app-tabs [data-view="'+view+'"]').click()
        assert style() == baseline
        expect(page.get_by_role('button',name='打开设置菜单')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    for path in ['/bookshelf','/market','/qihaoshou']:
        page.goto('http://ui.test'+path)
        assert style() == baseline
        expect(page.locator('.v3-topbar .stat b')).to_have_text('100')
        toggle=page.get_by_role('button',name='打开设置菜单')
        toggle.click()
        expect(page.locator('#settings-menu')).to_be_visible()
        menu=page.locator('#settings-menu').bounding_box()
        nav=page.locator('.v3-topbar').bounding_box()
        assert menu['x']>=nav['x']
        assert menu['x']+menu['width']<=nav['x']+nav['width']
        assert menu['y']>=nav['y']
        page.keyboard.press('Escape')
        expect(page.locator('#settings-menu')).to_be_hidden()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def test_embedded_pages_do_not_show_a_second_sidebar(ui):
    page, _ = ui
    page.set_viewport_size({'width':1440,'height':1000})
    for path in ['/bookshelf?embed=1','/market?embed=1','/qihaoshou?embedded=1']:
        page.goto('http://ui.test'+path)
        expect(page.locator('.v3-topbar')).to_be_hidden()
        expect(page.locator('#mint-settings-toggle')).to_have_count(0)


def test_standalone_settings_link_opens_existing_account_panel(ui):
    page, _ = ui
    page.set_viewport_size({'width':1440,'height':1000})
    page.goto('http://ui.test/bookshelf')
    page.get_by_role('button',name='打开设置菜单').click()
    page.locator('#settings-menu').get_by_role('menuitem',name='我的积分').click()
    expect(page.locator('#wallet-modal')).to_be_visible()
    assert 'sidebar=' not in page.url
