"""Resource navigation must preserve the document and hide unrelated views."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui
from pathlib import Path


@pytest.mark.parametrize('width', [390, 1440])
def test_market_navigation_keeps_document_and_hides_home(ui, width):
    page, state = ui
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto('http://ui.test/')
    page.evaluate('window.navigationSentinel = "same-document"')
    page.locator('.app-tabs [data-view=market]').evaluate('(el) => el.click()')
    expect(page.locator('#market')).to_be_visible()
    expect(page.locator('#home')).to_be_hidden()
    assert page.evaluate('window.navigationSentinel') == 'same-document'
    page.locator('.app-tabs [data-view=home]').evaluate('(el) => el.click()')
    expect(page.locator('#market')).to_be_hidden()
    expect(page.locator('#home')).to_be_visible()
    page.locator('.object-agents').click()
    expect(page.locator('#market')).to_be_visible()
    expect(page.locator('#home')).to_be_hidden()
    assert page.evaluate('window.navigationSentinel') == 'same-document'
    assert not state['errors']


@pytest.mark.parametrize('path', ['/', '/market'])
def test_slow_app_bundle_never_flashes_home_or_reloads_market(ui, path):
    page, _ = ui
    held = []
    documents = []
    page.on('request', lambda request: documents.append(request.url)
            if request.is_navigation_request() and request.frame == page.main_frame else None)
    page.route('**/static/app.js?*', lambda route: held.append(route))
    page.goto('http://ui.test' + path, wait_until='commit')
    page.locator('.app-tabs [data-view=market]').wait_for(state='attached')
    if path == '/market':
        expect(page.locator('#home')).to_be_hidden()
    page.evaluate('window.navigationSentinel = "loading-document"')
    page.locator('.app-tabs [data-view=market]').evaluate('(el) => el.click()')
    expect(page.locator('#home')).to_be_hidden()
    assert len(documents) == 1
    page.locator('script[src*="/static/app.js"]').wait_for(state='attached')
    assert held
    held[0].fulfill(content_type='application/javascript', body=(Path(__file__).resolve().parents[1] / 'static/app.js').read_bytes())
    expect(page.locator('#market')).to_be_visible()
    expect(page.locator('#home')).to_be_hidden()
    assert page.evaluate('window.navigationSentinel') == 'loading-document'
    assert page.url == 'http://ui.test/market'
    assert len(documents) == 1
