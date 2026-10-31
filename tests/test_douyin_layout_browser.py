from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


def test_douyin_workspace_responsive(ui):
    page, state = ui
    page.goto('http://ui.test/douyin-extract')
    for width in [1440, 390]:
        page.set_viewport_size({'width':width,'height':900})
        expect(page.locator('#douyin-extract-url')).to_be_visible()
        expect(page.locator('#douyin-extract-start')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not state['errors']
