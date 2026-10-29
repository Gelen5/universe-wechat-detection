"""One-click layout checks; all endpoints intercepted by the UI fixture."""
import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui  # noqa: F401

@pytest.mark.parametrize('width', [390, 768, 1024, 1440, 2560])
def test_oneclick_layout_remains_usable(ui, width):
    page, _ = ui
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto('http://ui.test/one-click-writing')
    frame = page.frame_locator('#one-click-writing-frame')
    topic = frame.locator('#q-topic')
    expect(topic).to_be_visible()
    expect(frame.locator('#q-generate')).to_be_visible()
    assert topic.evaluate('el => parseFloat(getComputedStyle(el).fontSize)') >= 15
    assert topic.evaluate('el => el.ownerDocument.documentElement.scrollWidth <= el.ownerDocument.documentElement.clientWidth + 1')
    if width == 2560:
        assert frame.locator('.studio').evaluate('el => el.getBoundingClientRect().width / el.ownerDocument.documentElement.clientWidth') > .95
        assert frame.locator('.settings').bounding_box()['width'] >= 330
    topic.fill('只填写主题即可生成')
    expect(topic).to_have_value('只填写主题即可生成')
    if os.getenv('ONECLICK_SCREENSHOT_DIR'):
        page.screenshot(path=str(Path(os.environ['ONECLICK_SCREENSHOT_DIR']) / f'oneclick-{width}.png'), full_page=True)
