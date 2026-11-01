import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui  # noqa: F401


@pytest.mark.parametrize('path,selector,endpoint', [
    ('/tie-tu', '[data-creation-history="tie-tu"]', '/api/creator/history?skill=tie-tu'),
    ('/viral-remix', '[data-creation-history="viral-remix"]', '/api/creator/history?skill=viral-remix'),
    ('/article-visual', '[data-creation-history="article-visual"]', '/api/article-visual/history/list'),
])
def test_history_entry_opens_and_loads(ui, path, selector, endpoint):
    page, observed = ui
    page.route('**/api/creator/history?*', lambda route: route.fulfill(json={'items': [{'id': 'a1', 'kind': 'chat', 'title': '旧创作', 'updated_at': '2026-11-01T10:00:00Z'}]}))
    page.route('**/api/article-visual/history/list*', lambda route: route.fulfill(json={'items': [{'id': 'a1', 'title': '旧创作', 'updated_at': '2026-11-01T10:00:00Z', 'image_count': 1}]}))
    page.goto('http://ui.test' + path)
    page.locator(selector).click()
    expect(page.locator('#creation-history-dialog')).to_be_visible()
    expect(page.locator('#creation-history-dialog')).to_contain_text('旧创作')
    page.locator('#creation-history-close').click()
    assert not observed['errors']


def test_article_history_restores_task(ui):
    page, observed = ui
    job = {'id': 'abc123', 'article': {'title': '已保存文章', 'chars': 20}, 'plan': {'thesis': '主题', 'article_type': 'knowledge', 'alternatives': []}, 'slots': [{'id': 'cover', 'form': 'cover', 'headline': '封面', 'status': 'done'}], 'images': {'cover': {'file': 'cover.png'}}}
    page.route('**/api/article-visual/history/list*', lambda route: route.fulfill(json={'items': [{'id': 'abc123', 'title': '已保存文章', 'updated_at': '2026-11-01T10:00:00Z', 'image_count': 1}]}))
    page.route('**/api/article-visual/abc123', lambda route: route.fulfill(json=job))
    page.goto('http://ui.test/article-visual')
    page.locator('[data-creation-history="article-visual"]').click()
    page.locator('.creation-history-item').click()
    expect(page.locator('#av-article-title')).to_have_text('已保存文章')
    assert 'job=abc123' in page.url
    page.locator('#av-new').click()
    assert 'job=' not in page.url
    assert not observed['errors']


def test_tie_form_plan_history_restores_images(ui):
    page, observed = ui
    plan = {'title': '旧计划', 'session_id': 'old-session', 'ratio': '3:4', 'portrait_enabled': False,
            'cards': [{'index': 1, 'overlay_text': '旧标题', 'caption': '说明', 'visual_subject': '茶杯'}],
            'images': [{'index': 1, 'url': '/api/creator-tools/assets/tie-tu/old/card-01.png'}]}
    page.route('**/api/creator/history?*', lambda route: route.fulfill(json={'items': [{'id': 'plan1', 'kind': 'plan', 'title': '旧计划', 'updated_at': '2026-11-01T10:00:00Z'}]}))
    page.route('**/api/creator/history/plan/plan1', lambda route: route.fulfill(json={'item': plan}))
    page.goto('http://ui.test/tie-tu')
    page.locator('[data-creation-history="tie-tu"]').click()
    page.locator('.creation-history-item').click()
    expect(page.locator('#tie-result')).to_contain_text('旧标题')
    expect(page.locator('#tie-result img')).to_have_count(1)
    page.locator('#tie-new').click()
    expect(page.locator('#tie-result')).to_be_hidden()
    assert not observed['errors']


def test_remix_local_draft_is_preserved_before_reset(ui):
    page, observed = ui
    saved = []
    page.route('**/api/creator/history/analysis/oldsession123', lambda route: (saved.append(route.request.post_data_json), route.fulfill(json={'status': 'saved'})))
    page.goto('http://ui.test/viral-remix')
    page.evaluate("""() => localStorage.setItem('viral-remix-draft:test-user', JSON.stringify({sessionId:'oldsession123', result:{content_guess:'旧拆解',ideas:[]}}))""")
    page.locator('#remix-new').click()
    page.wait_for_function("localStorage.getItem('viral-remix-draft:test-user') === null")
    assert saved[0]['result']['content_guess'] == '旧拆解'
    assert not observed['errors']


def test_remix_reset_keeps_draft_when_import_fails(ui):
    page, _ = ui
    page.route('**/api/creator/history/analysis/oldsession123', lambda route: route.fulfill(status=503, json={'detail': 'offline'}))
    page.goto('http://ui.test/viral-remix')
    page.evaluate("""() => localStorage.setItem('viral-remix-draft:test-user', JSON.stringify({sessionId:'oldsession123', result:{content_guess:'旧拆解',ideas:[]}}))""")
    page.locator('#remix-new').click()
    page.wait_for_timeout(500)
    assert page.evaluate("localStorage.getItem('viral-remix-draft:test-user')") is not None
