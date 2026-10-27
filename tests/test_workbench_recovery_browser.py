"""Real browser refresh/retry and optimistic editor conflict contracts."""
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


def writing_page(page):
    page.set_viewport_size({'width': 1440, 'height': 1000})
    article = dict(id='revision-1', type='article', title='Saved draft', version=1,
                   content='Original body', content_json={}, run_id='old',
                   created_at='2026-10-27T00:00:00Z')
    page.route('**/api/conversations/recent-1/artifacts*', lambda r: r.fulfill(json={'artifacts': [article]}))
    page.route('**/api/conversations/recent-1/messages', lambda r: r.fulfill(json={
        'messages': [{'role': 'user', 'content': 'Write a draft', 'content_json': {}}]}))
    page.add_init_script('window.EventSource=class {addEventListener(){}close(){}}')
    return article


@pytest.mark.parametrize('committed', [False, True])
@pytest.mark.parametrize('response_loss', ['connection', 'html_gateway', 'missing_run_id'])
def test_refresh_recovers_uncertain_post_without_creating_another_task(ui, committed, response_loss):
    page, _ = ui
    writing_page(page)
    posts = []
    accepted = []
    run = {'id': 'recovered-run', 'conversation_id': 'recent-1', 'status': 'running', 'stage': 'writing'}

    def messages(route):
        if route.request.method != 'POST':
            route.fallback()
            return
        posts.append(route.request.headers['idempotency-key'])
        if len(posts) == 1:
            if committed:
                accepted.append(run)
            if response_loss == 'connection': route.abort('connectionfailed')
            elif response_loss == 'html_gateway': route.fulfill(status=200, body='<html>gateway</html>', content_type='text/html')
            else: route.fulfill(json={})
        else:
            accepted.append(run)
            route.fulfill(json={'run_id': run['id']})

    page.route('**/api/conversations/recent-1/messages', messages)
    page.route('**/api/conversations/recent-1/requests/*', lambda route: route.fulfill(
        status=200 if accepted else 404, json={'run': run} if accepted else {'detail': 'not recorded'}))
    page.route('**/api/runs/recovered-run', lambda route: route.fulfill(json={'run': run}))
    page.goto('http://ui.test/workbench?conversation=recent-1', wait_until='networkidle')
    page.locator('#workbench-topic').fill('Improve the factual explanation')
    page.locator('#start-workbench').click()
    expect(page.locator('#start-workbench')).to_be_enabled()
    assert page.evaluate('JSON.parse(sessionStorage.getItem("universe.conversation.pendingRequest")).key') == posts[0]
    page.reload(wait_until='networkidle')
    if not committed:
        expect(page.locator('#workbench-topic')).to_have_value('Improve the factual explanation')
        page.locator('#start-workbench').click()
    page.wait_for_function('localStorage.getItem("universe.conversation.activeRun") === "recovered-run"')
    assert len(accepted) == 1
    assert len(posts) == (1 if committed else 2)
    assert len(set(posts)) == 1
    assert page.evaluate('sessionStorage.getItem("universe.conversation.pendingRequest")') is None


def test_editor_conflict_keeps_unsaved_text_and_blocks_paid_action(ui):
    page, _ = ui
    original = writing_page(page)
    posts = []
    conflict = []
    latest = dict(original, id='revision-2', version=2, content='Other tab saved this body')
    page.route('**/api/conversations/recent-1/artifacts*', lambda route: route.fulfill(
        json={'artifacts': [latest if conflict else original]}))
    def save(route):
        assert route.request.post_data_json['expected_current_id'] == 'revision-1'
        conflict.append(True)
        route.fulfill(status=409, json={'detail': 'A newer version was saved in another page'})
    page.route('**/api/artifacts/revision-1/versions', save)
    page.route('**/api/conversations/recent-1/messages', lambda route: (
        posts.append(route.request.post_data_json), route.fulfill(json={'run_id': 'should-not-exist'})
    ) if route.request.method == 'POST' else route.fallback())
    page.add_init_script('window.copied=[];Object.defineProperty(navigator,"clipboard",{value:{writeText:async value=>window.copied.push(value)}})')
    page.goto('http://ui.test/workbench?conversation=recent-1', wait_until='networkidle')
    page.locator('#edit-current').click()
    page.locator('#article-editor').fill('My unsaved important changes')
    page.locator('#workbench-topic').fill('Revise this')
    page.locator('#start-workbench').click()
    expect(page.get_by_role('button', name='复制未保存正文')).to_be_visible()
    expect(page.locator('#article-editor')).to_have_value('My unsaved important changes')
    assert posts == []
    page.get_by_role('button', name='复制未保存正文').click()
    assert page.evaluate('window.copied') == ['My unsaved important changes']
    page.on('dialog', lambda dialog: dialog.accept())
    page.get_by_role('button', name='读取最新版本').click()
    expect(page.locator('#article-editor')).to_have_value('Other tab saved this body')
