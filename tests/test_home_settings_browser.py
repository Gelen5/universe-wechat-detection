"""Brand entry navigation and settings layout using intercepted APIs only."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


def test_first_visit_home_and_creation_open_login_when_unauthenticated(ui):
    page, _ = ui
    page.route('**/api/auth/me', lambda route: route.fulfill(status=401, json={'detail': '登录后使用'}))
    page.goto('http://ui.test/')
    expect(page.locator('.universe-brand')).to_be_visible()
    expect(page.locator('#auth-modal')).to_be_visible()
    expect(page.locator('#logout-button')).to_have_text('登录 / 注册')
    page.goto('http://ui.test/workbench')
    expect(page.locator('#auth-modal')).to_be_visible()


def test_valid_session_enters_home_without_login_popup(ui):
    page, _ = ui
    page.goto('http://ui.test/')
    expect(page.locator('#wallet-balance')).to_have_text('100')
    expect(page.locator('#auth-modal')).to_be_hidden()
    expect(page.locator('#logout-button')).to_have_text('退出登录')


@pytest.mark.parametrize('width', [390, 1101, 1440, 1920, 2560])
def test_brand_canvas_and_entry_have_no_overflow_or_overlapping_controls(ui, width):
    page, state = ui
    page.set_viewport_size({'width': width, 'height': 1080})
    page.goto('http://ui.test/')
    stage = page.locator('.universe-stage')
    assert stage.bounding_box()['width'] > width / 2
    expect(stage.locator('h1')).to_have_text('宇宙第一工作台.')
    expect(stage).to_contain_text('你的想法，不必止于想想。')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.get_by_role('link', name='从一个想法开始').click()
    expect(page.locator('#universe-entry-title')).to_be_in_viewport()
    page.get_by_role('link', name='换种表达').click()
    page.wait_for_url('**/xiaohongshu')
    assert not any(x.endswith('/generate') or x.endswith('/chat') for x in state['requests'])


@pytest.mark.parametrize('width', [390, 1440, 1920])
def test_owner_settings_keep_real_controls_and_readable_width(ui, width):
    page, _ = ui
    page.set_viewport_size({'width': width, 'height': 1000})
    wallet = {'balance': 125, 'trial': 100, 'bonus': 25, 'paid': 0}
    user = {'id': 'owner', 'email': 'gelen5@163.com', 'display_name': '管理员', 'role': 'admin', 'balance': 125, 'completed_tasks': 2, 'created_at': '2026-10-25T00:00:00Z'}
    def api(route):
        path = route.request.url.split('ui.test')[1].split('?')[0]
        if path == '/api/auth/me': data = {'user': user, 'wallet': wallet}
        elif path == '/api/admin/overview': data = {'overview': {'users': 1, 'registered_today': 1, 'registered_7d': 1, 'active_30d': 1}}
        elif path == '/api/admin/users': data = {'users': [user]}
        elif path == '/api/admin/tasks': data = {'tasks': []}
        elif path == '/api/admin/provider-settings': data = {'settings': {'text_base_url': 'https://example.test/v1', 'text_model': 'test-model', 'text_configured': True}}
        elif path == '/api/wallet': data = {'wallet': wallet, 'transactions': []}
        else: route.fallback(); return
        route.fulfill(json=data)
    page.route('**/api/**', api)
    page.goto('http://ui.test/')
    for action, modal in [('api-settings-button', 'api-settings'), ('admin-users-button', 'admin-users'), ('wallet-settings-button', 'wallet')]:
        if width > 1100:
            page.get_by_role('button', name='打开设置菜单').click()
        else:
            page.wait_for_function("!document.getElementById('api-settings-button').hidden")
            page.get_by_role('button', name='更多', exact=True).click()
        if width > 1100:
            page.locator('#' + action).click()
        else:
            label = {'api-settings-button':'API 设置', 'admin-users-button':'用户统计',
                     'wallet-settings-button':'我的积分'}[action]
            page.get_by_role('region', name='账号管理').get_by_role('button', name=label, exact=True).click()
            expect(page.locator('#shell-more-menu')).not_to_be_visible()
        dialog = page.locator('#' + modal + '-modal [role=dialog]')
        expect(dialog).to_be_visible()
        box = dialog.bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= width
        assert dialog.evaluate('e=>e.scrollWidth <= e.clientWidth + 1')
        if modal == 'api-settings':
            expect(page.locator('#shared-text-model')).to_have_value('test-model')
            expect(page.locator('#api-settings-save')).to_be_visible()
        if modal == 'admin-users':
            expect(page.locator('#admin-users-list')).to_contain_text('管理员')
            if width > 1100: assert box['width'] > 1000
        if modal == 'wallet':
            expect(page.locator('#wallet-modal-balance')).to_have_text('125')
            expect(page.locator('#admin-recharge-panel')).to_be_visible()
        page.locator('#' + modal + '-close').click()
        expect(dialog).to_be_hidden()
