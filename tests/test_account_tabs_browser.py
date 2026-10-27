"""Shared-cookie identity changes must invalidate private state in other tabs."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


@pytest.mark.parametrize('next_identity', ['second-user', None])
def test_other_tab_refreshes_identity_and_clears_private_surfaces(ui, next_identity):
    first, _ = ui
    context = first.context
    identity = {'id': 'first-user'}
    reads = []

    def account(route):
        reads.append(identity['id'])
        if identity['id'] is None:
            route.fulfill(status=401, json={'detail': 'Login required'})
        else:
            route.fulfill(json={'user': {'id': identity['id'], 'display_name': identity['id'],
                'email': 'test@example.test', 'role': 'user'}, 'wallet': {'balance': 100}})

    context.route('**/api/auth/me', account)
    first.goto('http://ui.test/workbench', wait_until='networkidle')
    second = context.new_page()
    second.goto('http://ui.test/workbench', wait_until='networkidle')
    first.wait_for_function("currentAccount?.id === 'first-user'")
    second.wait_for_function("currentAccount?.id === 'first-user'")
    second.evaluate('''() => {
        document.querySelector('#xhs-result').textContent = 'Private old result';
        document.querySelector('#wallet-modal').hidden = false;
        document.querySelector('#shared-text-api-key').value = 'private-test-value';
    }''')
    identity['id'] = next_identity
    first.evaluate('loadAccount()')
    second.wait_for_function('(expected) => (currentAccount?.id || null) === expected', arg=next_identity)
    expect(second.locator('#wallet-modal')).to_be_hidden()
    expect(second.locator('#xhs-result')).to_be_empty()
    expect(second.locator('#shared-text-api-key')).to_have_value('')
    assert len(reads) < 12, 'Account invalidation must not loop between tabs'
    second.close()


def test_transient_account_lookup_failure_preserves_current_identity(ui):
    page, _ = ui
    page.goto('http://ui.test/workbench', wait_until='networkidle')
    page.route('**/api/auth/me', lambda route: route.fulfill(status=503, json={'detail': 'Temporary outage'}))
    page.evaluate('loadAccount()')
    assert page.evaluate('currentAccount.id') == 'test-user'


def test_late_private_response_cannot_update_wallet_or_render(ui):
    page, _ = ui
    page.goto('http://ui.test/workbench', wait_until='networkidle')
    result = page.evaluate('''async () => {
        try {
            await readApiResponse(new Response(JSON.stringify({private: 'old account data'}), {
                headers: {'Content-Type': 'application/json', 'X-Account-ID': 'previous-user',
                          'X-Points-Balance': '99999'}}));
            return 'incorrectly accepted';
        } catch (error) { return error.message; }
    }''')
    assert '账号已切换' in result
    assert page.evaluate('currentWallet.balance') == 100


def test_account_switch_waits_for_save_and_stops_on_failure(ui):
    page, _ = ui
    page.goto('http://ui.test/workbench', wait_until='networkidle')
    logout_requests = []
    page.route('**/api/auth/logout', lambda route: (
        logout_requests.append(True), route.fulfill(json={})))
    result = page.evaluate('''async () => {
        window.addEventListener('before-account-change', event => {
            event.detail.pending.push(Promise.reject(new Error('草稿保存失败')));
        }, {once: true});
        document.querySelector('#logout-button').click();
        await new Promise(resolve => setTimeout(resolve, 100));
        return currentAccount.id;
    }''')
    assert result == 'test-user'
    assert not logout_requests
    page.evaluate('''() => {
        window.addEventListener('before-account-change', event => {
            event.detail.pending.push(new Promise(resolve => { window.finishTestSave = resolve; }));
        }, {once: true});
        document.querySelector('#logout-button').click();
    }''')
    assert not logout_requests
    page.evaluate('finishTestSave()')
    page.wait_for_function('currentAccount === null')
    assert len(logout_requests) == 1


@pytest.mark.parametrize('status', [200, 401, 500])
def test_logout_accepts_expired_session_but_does_not_hide_server_failure(ui, status):
    page, _ = ui
    page.goto('http://ui.test/workbench', wait_until='networkidle')
    page.route('**/api/auth/logout', lambda route: route.fulfill(status=status, json={}))
    page.evaluate("document.querySelector('#logout-button').click()")
    if status == 500:
        expect(page.get_by_text('退出未确认，请稍后重试', exact=True)).to_be_visible()
        assert page.evaluate('currentAccount.id') == 'test-user'
    else:
        page.wait_for_function('currentAccount === null')
        expect(page.locator('#auth-modal')).to_be_visible()
        assert page.evaluate('currentWallet.balance') == 0
        expect(page.get_by_text('退出未确认，请稍后重试', exact=True)).to_have_count(0)
