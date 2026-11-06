import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

@pytest.mark.parametrize('width', [390, 1440])
def test_checkin_ui_status_and_duplicate_protection(ui, width):
    page, state = ui
    page.set_viewport_size({'width': width, 'height':900})
    issued = {'checked':False, 'posts':0}
    def checkin(route):
        if route.request.method == 'POST':
            issued['posts'] += 1; issued['checked'] = True
            route.fulfill(json={'checked_in':True,'credited':True,'points':5,'wallet':{'balance':105,'bonus':5}})
        else:
            route.fulfill(json={'checked_in':issued['checked'],'points':5,'day':'2026-11-06'})
    page.route('**/api/checkin',checkin)
    page.goto('http://ui.test/')
    card = page.locator('.daily-checkin-home' if width == 390 else '.daily-checkin-sidebar')
    expect(card).to_be_visible()
    button = card.locator('button')
    expect(button).to_have_text('签到领 5 分')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    if os.getenv('CHECKIN_SHOTS'):
        page.screenshot(path=str(Path(os.environ['CHECKIN_SHOTS']) / f'checkin-before-{width}.png'),full_page=True)
    button.click()
    expect(button).to_have_text('今日已签到')
    expect(button).to_be_disabled()
    expect(card.locator('[role=status]')).to_have_text('+5 积分已到账')
    assert issued['posts'] == 1
    if os.getenv('CHECKIN_SHOTS'):
        page.screenshot(path=str(Path(os.environ['CHECKIN_SHOTS']) / f'checkin-after-{width}.png'),full_page=True)
