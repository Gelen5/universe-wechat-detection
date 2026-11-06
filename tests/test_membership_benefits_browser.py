import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

PACKAGES = [{'id':'week','name':'周卡','price':'9.90','days':7,'credits':30},
            {'id':'month','name':'月卡','price':'29.90','days':30,'credits':80},
            {'id':'year','name':'年卡','price':'199.00','days':365,'credits':80,'periods':12}]

@pytest.mark.parametrize('width',[390,1440])
def test_membership_purchase_and_low_points_guidance(ui, width):
    page,_ = ui
    page.set_viewport_size({'width':width,'height':900})
    page.route('**/api/viral-insights/membership', lambda r:r.fulfill(json={
        'enabled':True,'active':True,'status':'member_active','packages':PACKAGES,
        'membership_expires_at':'2026-12-06T00:00:00+00:00','credit_next_at':'2026-11-20T00:00:00+00:00'}))
    page.goto('http://ui.test/')
    page.evaluate('ViralInsightsMembership.open()')
    modal=page.locator('#viral-insights-membership-modal')
    expect(modal).to_be_visible()
    expect(modal).to_contain_text('含 30 积分')
    expect(modal).to_contain_text('含 80 积分')
    expect(modal).to_contain_text('每期 80 分 × 12')
    expect(modal).to_contain_text('退款将终止')
    page.locator('[data-vi-package=year]').click()
    expect(page.locator('[data-vi-buy]')).to_have_text('开通年卡')
    box=modal.locator('.vi-card').bounding_box()
    assert box['x'] >= 0 and box['x']+box['width'] <= width + 1
    if os.getenv('MEMBER_SHOTS'): page.screenshot(path=str(Path(os.environ['MEMBER_SHOTS'])/f'member-{width}.png'))
    page.locator('[data-vi-close]').click()
    page.evaluate("PointsNotice.open('积分不足：需要 2 积分，当前剩余 0 积分')")
    dialog=page.locator('#points-notice')
    expect(dialog).to_be_visible()
    expect(dialog.locator('#points-notice-member-hint')).to_contain_text('选题权限不受影响')
    expect(dialog.locator('#points-notice-member-hint')).to_contain_text('签到')
    page.keyboard.press('Escape')

