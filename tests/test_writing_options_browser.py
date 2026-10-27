"""Verify optional choices do not block the real one-click writing UI."""
import json
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


@pytest.mark.parametrize('use_options', [False, True])
def test_one_click_can_generate_and_restore_with_or_without_optional_choices(ui, use_options):
    page, _ = ui
    saved = []
    state = {}

    def sessions(route):
        if route.request.method == 'POST':
            state.update(route.request.post_data_json)
            state.update(id='writer_123', revision=0)
            saved.append(dict(state))
            route.fulfill(json=state)
        else:
            route.fulfill(json={'sessions': []})

    def generate(route):
        completed = dict(state, revision=1, html='<h1>结果</h1><p>正文已生成</p>')
        payload = 'data: ' + json.dumps({'article': completed, 'done': True}, ensure_ascii=False) + '\n\n'
        route.fulfill(status=200, content_type='text/event-stream', body=payload)

    page.route('**/api/qihaoshou/sessions', sessions)
    page.route('**/api/qihaoshou/generate', generate)
    page.add_init_script("if (!crypto.randomUUID) crypto.randomUUID = () => 'browser-test-request-123';")
    page.goto('http://ui.test/qihaoshou', wait_until='networkidle')
    page.locator('#q-topic').fill('写一篇读者能用上的文章')
    if use_options:
        page.locator('#q-writing-options summary').click()
        page.locator('#q-writing_goal').select_option(label='学会操作')
        page.locator('#q-content_form').select_option(label='实操教程')
        page.locator('#q-author_material').fill('我已有一份字段清单')
    page.locator('#q-generate').click()
    expect(page.locator('#q-status')).to_have_text('文章已生成并保存，可以编辑和排版')
    assert saved[0]['writing_goal'] == ('学会操作' if use_options else '')
    assert saved[0]['content_form'] == ('实操教程' if use_options else '')
    assert saved[0]['author_material'] == ('我已有一份字段清单' if use_options else '')
    expect(page.frame_locator('#q-editor').locator('body')).to_contain_text('正文已生成')
    if use_options:
        expect(page.locator('#q-author_material')).to_have_value('我已有一份字段清单')
