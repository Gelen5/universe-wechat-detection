"""Exercise saved input, account teardown and uncertain POSTs through the real UI."""
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('width', [390, 1440])
def test_history_loads_body_only_when_opened_and_can_page_back(ui, width):
    page, _ = ui
    page.set_viewport_size({'width': width, 'height': 1000})
    stamp = '2026-10-27T00:00:00Z'
    newest = dict(id='new', type='article', title='Latest draft', version=3,
                  content='Latest body', content_json={}, content_loaded=True,
                  run_id='r', created_at=stamp)
    old = dict(newest, id='old', version=2, title='Previous draft', content_loaded=False,
               created_at='2026-10-26T00:00:00Z')
    old.pop('content')
    old.pop('content_json')
    oldest = dict(old, id='oldest', version=1, title='First draft', created_at='2026-10-25T00:00:00Z')
    calls = []

    def history(route):
        calls.append(route.request.url)
        if 'before=' in route.request.url:
            route.fulfill(json={'artifacts': [newest, oldest], 'total': 3, 'next_cursor': None})
        else:
            route.fulfill(json={'artifacts': [newest, old], 'total': 3, 'next_cursor': 'old'})

    page.route('**/api/conversations/recent-1/artifacts*', history)
    page.route('**/api/conversations/recent-1/messages', lambda route: route.fulfill(json={
        'messages': [{'role': 'user', 'content': 'Write a draft', 'content_json': {}}]}))
    page.route('**/api/artifacts/old', lambda route: route.fulfill(json={'artifact': dict(old, content='Earlier body', content_json={})}))
    page.route('**/api/artifacts/oldest', lambda route: route.fulfill(json={'artifact': dict(oldest, content='First body', content_json={})}))
    page.goto('http://ui.test/workbench?conversation=recent-1', wait_until='networkidle')
    if width < 1101:
        page.locator('#workbench-view-toggle').click()
    page.locator('.artifact-history summary').click()
    page.locator('[data-artifact-id="old"]').click()
    expect(page.locator('#article-editor')).to_have_value('Earlier body')
    page.locator('[data-more-artifacts]').click()
    page.locator('[data-artifact-id="oldest"]').wait_for()
    page.locator('[data-artifact-id="oldest"]').click()
    expect(page.locator('#article-editor')).to_have_value('First body')
    expect(page.locator('[data-more-artifacts]')).to_have_count(0)
    assert len(calls) == 2


@pytest.mark.parametrize('slow_save', [False, True])
def test_editor_saves_before_submit_and_identity_change_clears_the_workspace(browser, slow_save):
    requests = []
    user = {'id': 'a', 'display_name': 'A', 'email': 'a@example.test', 'role': 'user'}
    items = [dict(id='article-1', type='article', title='Private draft A', content='Original draft',
                  content_json={}, version=1, run_id='old', created_at='2026-10-27T00:00:00Z')]
    items.insert(0, dict(id='image-a', type='image', title='Private image A', content='', content_json={},
        version=1, run_id='old', created_at='2026-10-27T00:00:00Z', storage_url='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jE8sAAAAASUVORK5CYII='))

    def serve(route):
        path = urlparse(route.request.url).path
        if not path.startswith('/api/'):
            file = ROOT / path.lstrip('/') if path.startswith('/static/') else ROOT / 'static/index.html'
            route.fulfill(status=200 if file.is_file() else 404,
                          body=file.read_bytes() if file.is_file() else b'',
                          content_type=mimetypes.guess_type(str(file))[0] or 'application/octet-stream')
            return
        data = {}
        if path == '/api/auth/me':
            data = {'user': user, 'wallet': {'balance': 100}}
        elif path == '/api/conversations/c':
            data = {'conversation': {'id': 'c', 'mode': 'manual', 'skill_id': 'wechat_writer'}}
        elif path.endswith('/artifacts'):
            data = {'artifacts': items}
        elif path.endswith('/versions'):
            requests.append(('save', route.request.post_data_json['content']))
            items.append(dict(items[-1], id='article-2', version=2,
                              content=route.request.post_data_json['content']))
            data = {'artifact': items[-1]}
        elif path.endswith('/messages') and route.request.method == 'POST':
            requests.append(('submit', route.request.headers['idempotency-key']))
            if len([item for item in requests if item[0] == 'submit']) == 1:
                route.abort('connectionfailed')
                return
            data = {'run_id': 'r'}
        elif path.endswith('/messages'):
            data = {'messages': []}
        elif path.startswith('/api/runs/'):
            data = {'run': {'id': 'r', 'status': 'running', 'stage': 'writing'}}
        route.fulfill(json=data)

    try:
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http://trust.test/**', serve)
        page.add_init_script('window.EventSource=class{addEventListener(){}close(){}}')
        if slow_save:
            page.add_init_script('''const originalFetch = window.fetch;
                window.fetch = async (...args) => {
                  if (String(args[0]).endsWith('/versions')) await new Promise(resolve => setTimeout(resolve, 700));
                  return originalFetch(...args);
                };''')
        page.goto('http://trust.test/workbench?conversation=c', wait_until='networkidle')
        # Restoring an article-only conversation must open its existing writing stage.
        expect(page.locator('#article-editor')).to_have_value('Original draft')
        expect(page.locator('#generated-images img')).to_have_count(1)
        expect(page.locator('#workbench-action-card [data-next-stage="deai"]')).to_be_visible()
        page.locator('#edit-current').click()
        expect(page.locator('#article-editor')).to_be_visible()
        if slow_save:
            page.locator('#article-editor').fill('Intermediate edit being saved')
            page.wait_for_timeout(1000)  # Real debounce is 900ms; request remains in flight.
        page.locator('#article-editor').fill('Edited fact that must be saved first')
        page.locator('#workbench-topic').fill('Revise this draft')
        page.locator('#start-workbench').click()
        expect(page.locator('#start-workbench')).to_be_enabled()
        first_submit = next(index for index, item in enumerate(requests) if item[0] == 'submit')
        assert requests[first_submit - 1] == ('save', 'Edited fact that must be saved first')
        if slow_save:
            assert requests[0] == ('save', 'Intermediate edit being saved')
        page.locator('#start-workbench').click()
        expect(page.locator('#start-workbench')).to_be_disabled()
        page.wait_for_function('localStorage.getItem("universe.conversation.activeRun") === "r"')
        keys = [value for kind, value in requests if kind == 'submit']
        assert len(keys) == 2 and keys[0] == keys[1]
        expect(page.locator('[data-workbench-stage="writing"] small')).to_have_text('更新中')
        user.update(id='b', display_name='B', email='b@example.test')
        page.evaluate('loadAccount()')
        expect(page.locator('#article-editor')).to_have_value('')
        assert 'Private draft A' not in page.locator('#workbench').inner_text()
        expect(page.locator('#generated-images img')).to_have_count(0)
        expect(page.locator('#generated-images')).not_to_be_visible()
        assert page.evaluate('localStorage.getItem("universe.conversation.activeRun")') is None
        assert not errors, errors
    finally:
        page.close()
