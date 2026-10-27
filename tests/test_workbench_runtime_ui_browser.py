import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui
from tests.test_workbench_recovery_browser import writing_page


def running_fixture(page):
    writing_page(page)
    run = {'id': 'run-ui', 'conversation_id': 'recent-1', 'status': 'queued', 'stage': 'writing',
           'conversation_title': 'Background article', 'created_at': '2026-10-27T00:00:00Z'}
    offline = []
    page.route('**/api/conversations/recent-1', lambda route: route.fulfill(json={
        'conversation': {'id': 'recent-1', 'mode': 'manual', 'skill_id': 'wechat_writer', 'active_run': run}}))
    page.route('**/api/runs/run-ui', lambda route: route.abort('connectionfailed') if offline else route.fulfill(json={'run': run}))
    page.route('**/api/runs?*', lambda route: route.fulfill(json={'runs': [] if run['status'] == 'cancelled' else [run]}))
    def cancel(route):
        run['status'] = 'cancelled'
        route.fulfill(json={'run': run})
    page.route('**/api/runs/run-ui/cancel', cancel)
    page.add_init_script('''window.sources=[];
        window.EventSource=class {
          constructor(){this.listeners={};this.seq=0;window.sources.push(this)}
          addEventListener(type,fn){this.listeners[type]=fn} close(){this.closed=true}
          emit(type,payload={}){this.listeners[type]?.({data:JSON.stringify({payload}),lastEventId:String(++this.seq)})}
        };''')
    return run, offline


@pytest.mark.parametrize('width', [390, 1440])
def test_queue_reconnect_and_cancel_have_one_truthful_status_card(ui, width):
    page, _ = ui
    run, offline = running_fixture(page)
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto('http://ui.test/workbench?conversation=recent-1', wait_until='networkidle')
    card = page.locator('#workbench-action-card')
    expect(card.locator('strong')).to_have_text('任务已排队')
    expect(page.locator('#workbench-progress')).not_to_be_visible()
    expect(page.locator('[data-cancel-run]')).to_be_visible()
    run['status'] = 'running'
    page.evaluate("window.sources.at(-1).emit('run.started')")
    expect(card.locator('strong')).to_have_text('正在执行：写作')
    assert card.locator('strong').bounding_box()['y'] >= page.locator('#workbench-chat-thread').bounding_box()['y'] - 1
    offline.append(True)
    page.evaluate('window.sources.at(-1).onerror()')
    expect(card.locator('strong')).to_have_text('连接中断，正在恢复')
    expect(page.locator('#start-workbench')).to_be_disabled()
    page.evaluate('''const real=window.fetch;window.fetch=(...args)=>String(args[0]).endsWith('/cancel')
      ? new Promise(resolve=>window.releaseCancel=()=>resolve(real(...args))) : real(...args);''')
    page.locator('[data-cancel-run]').click()
    page.wait_for_function('typeof window.releaseCancel === "function"')
    page.evaluate("window.sources.at(-1).emit('tool.progress',{step:'generating',status:'running'})")
    expect(card.locator('strong')).to_have_text('正在取消任务')
    expect(page.locator('[data-cancel-run]')).to_be_disabled()
    offline.clear()
    page.evaluate('window.releaseCancel()')
    expect(card.locator('strong')).to_have_text('任务已取消')
    expect(page.locator('#start-workbench')).to_be_enabled()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


@pytest.mark.parametrize('width', [390, 1440])
def test_task_can_be_reentered_after_new_chat_without_a_local_run_pointer(ui, width):
    page, _ = ui
    running_fixture(page)
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto('http://ui.test/workbench?conversation=recent-1', wait_until='networkidle')
    page.locator('#new-workbench-chat').click()
    page.wait_for_function('!localStorage.getItem("universe.conversation.activeRun")')
    assert 'conversation=' not in page.url
    page.locator('#active-workbench-runs').click()
    expect(page.locator('#workbench-task-list')).to_contain_text('Background article')
    page.locator('#workbench-task-list [data-conversation-id]').click()
    page.wait_for_function('localStorage.getItem("universe.conversation.activeRun")==="run-ui"')
    expect(page.locator('#workbench-action-card strong')).to_have_text('任务已排队')
    page.locator('#active-workbench-runs').click()
    page.keyboard.press('Escape')
    expect(page.locator('#active-workbench-runs')).to_be_focused()
    expect(page.locator('#workbench-task-list')).not_to_be_visible()


def test_cancel_event_wins_over_a_late_http_failure(ui):
    page, _ = ui
    run, _ = running_fixture(page)
    page.route('**/api/runs/run-ui/cancel', lambda route: route.abort('connectionfailed'))
    page.goto('http://ui.test/workbench?conversation=recent-1', wait_until='networkidle')
    page.evaluate('''const real=window.fetch;window.fetch=(...args)=>String(args[0]).endsWith('/cancel')
      ? new Promise(resolve=>window.releaseCancel=()=>resolve(real(...args))) : real(...args);''')
    page.locator('[data-cancel-run]').click()
    page.wait_for_function('typeof window.releaseCancel === "function"')
    run['status'] = 'cancelled'
    page.evaluate("window.sources.at(-1).emit('run.cancelled')")
    expect(page.locator('#workbench-action-card strong')).to_have_text('任务已取消')
    page.evaluate('window.releaseCancel()')
    page.wait_for_timeout(100)
    expect(page.locator('#workbench-chat-thread')).not_to_contain_text('取消结果尚未确认')


def test_task_pagination_retains_first_page_and_loads_more(ui):
    page, _ = ui
    run, _ = running_fixture(page)
    queries = []
    def pages(route):
        queries.append(route.request.url)
        route.fulfill(json={'runs': [{**run, 'id': 'older', 'conversation_title': 'Earlier task'}], 'next_cursor': None}
                      if 'before=' in route.request.url else {'runs': [run], 'next_cursor': 'run-ui'})
    page.route('**/api/runs?*', pages)
    page.goto('http://ui.test/workbench?conversation=recent-1', wait_until='networkidle')
    page.locator('#active-workbench-runs').click()
    page.locator('[data-more-runs]').click()
    expect(page.locator('#workbench-task-list')).to_contain_text('Earlier task')
    expect(page.locator('#workbench-task-list')).to_contain_text('Background article')
    expect(page.locator('[data-more-runs]')).to_have_count(0)
    assert 'before=run-ui' in queries[-1]


def test_failed_cancel_remains_retryable_without_browser_error_text(ui):
    page, _ = ui
    running_fixture(page)
    calls = []
    def fail(route):
        calls.append(route.request.url)
        route.abort('connectionfailed')
    page.route('**/api/runs/run-ui/cancel', fail)
    page.goto('http://ui.test/workbench?conversation=recent-1', wait_until='networkidle')
    page.locator('[data-cancel-run]').click()
    expect(page.locator('#workbench-action-card strong')).to_have_text('取消结果待确认')
    expect(page.locator('[data-cancel-run]')).to_be_enabled()
    page.locator('[data-cancel-run]').click()
    expect(page.locator('[data-cancel-run]')).to_be_enabled()
    assert len(calls) == 2
    expect(page.locator('#workbench-chat-thread')).not_to_contain_text('Failed to fetch')
