"""Interaction regression with explicit API fixtures; not provider acceptance."""
from copy import deepcopy
import json
from urllib.parse import urlparse

from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


def plus_fixture(page):
    state = {'messages':[], 'article_state':None, 'choices':[], 'versions':[]}
    row = {'id':'plus-browser', 'title':'会议记录', 'version':1, 'state':state, 'turns':[]}
    requests = []

    def serve(route):
        request = route.request
        path = urlparse(request.url).path
        data = request.post_data_json if request.method in {'POST','PUT'} else {}
        requests.append((request.method, path, data))
        if path.endswith('/preview'):
            route.fulfill(content_type='text/html', body='<section style="color:#214d3d"><h2>会议记录</h2><p>排版后的正文</p><script>danger()</script></section>')
            return
        if path.endswith('/sessions') and request.method == 'GET':
            body = {'sessions':[row] if row['state']['messages'] else [], 'pricing':'Plus 内测期间暂不扣积分'}
        elif path.endswith('/sessions'):
            body = {'session':row}
        elif path.endswith('/messages'):
            state['messages'].append({'role':'user','content':data['message']})
            if data['message'] in {'排版看看','简约清爽','换一种排版'}:
                state['article_state']['formatted_output'] = '/private/article.html'
                state['messages'].append({'role':'assistant','content':'排版完成。'})
                state['last_action'] = 'format'
                state['layout_theme'] = {'id':'clean','name':'简约清爽'}
                state['reply_options'] = ['换一种排版','简约清爽','专业科技','温暖故事']
            elif not state['choices'] and not state['article_state']:
                state['choices'] = [{'title':'会议结束后，怎样确认待办','angle':'从讨论到行动'}, {'title':'AI会议摘要为什么漏信息','angle':'核对原始材料'}]
                state['messages'].append({'role':'assistant','content':'选一个切入点。'})
            else:
                state['choices'] = []
                state['article_state'] = {'draft':'# 会议记录\n\n这是一篇用于交互回归的测试正文。', 'quality_report':{}, 'evidence_pack':{}, 'formatted_output':''}
                state['versions'] = [{'number':1,'draft':state['article_state']['draft'],'reason':'生成初稿'}]
                state['messages'].append({'role':'assistant','content':'正文已放到右侧。'})
                state['last_action'] = 'write'
                state['reply_options'] = ['简约清爽','专业科技','温暖故事','帮我选']
            row['version'] += 1
            row['turns'] = [{'id':'turn-'+str(row['version']), 'status':'completed', 'message':data['message'], 'created_at':'2026-10-31T00:00:00Z'}]
            body = {'turn':row['turns'][0]}
        elif path.endswith('/draft'):
            state['article_state']['draft'] = data['draft']
            state['versions'].append({'number':2,'draft':data['draft'],'reason':'手动编辑'})
            row['version'] += 1
            body = {'session':row}
        else:
            body = {'session':row}
        route.fulfill(status=202 if path.endswith('/messages') else 200, json=deepcopy(body))

    page.route('**/api/wechat-plus/**', serve)
    return requests


def test_plus_entry_multiturn_edit_and_refresh(ui):
    page, observed = ui
    page.set_viewport_size({'width':1440,'height':1000})
    requests = plus_fixture(page)
    page.goto('http://ui.test/workbench')
    page.get_by_role('link', name='公众号创作 Plus', exact=True).click()
    expect(page).to_have_url('http://ui.test/wechat-plus')
    expect(page.locator('#wechat-plus')).to_be_visible()
    page.locator('[data-wp-input]').fill('给上班族写会议记录，先帮我选题')
    page.locator('[data-wp-send]').click()
    page.wait_for_function("document.querySelector('.wp-topic') || !document.querySelector('[data-wp-error]').hidden")
    assert page.locator('[data-wp-error]').is_hidden(), page.locator('[data-wp-error]').inner_text()
    page.get_by_role('button', name='1. 会议结束后，怎样确认待办').wait_for()
    page.get_by_role('button', name='1. 会议结束后，怎样确认待办').click()
    editor = page.locator('[data-wp-editor]')
    # A terminal submission is reloaded too; no active task is needed to fetch it.
    page.reload()
    expect(editor).to_have_value('# 会议记录\n\n这是一篇用于交互回归的测试正文。')
    editor.fill('# 会议记录\n\n手动补充一段材料。')
    page.locator('[data-wp-save]').click()
    expect(page.locator('[data-wp-save-state]')).to_have_text('已保存')
    page.reload()
    expect(editor).to_have_value('# 会议记录\n\n手动补充一段材料。')
    assert len([r for r in requests if r[1].endswith('/messages')]) == 2
    page.get_by_role('link', name='热点广场', exact=True).click()
    expect(page.locator('#hotspots')).to_be_visible()
    expect(page.locator('#wechat-plus')).to_be_hidden()
    assert not observed['errors']


def test_plus_mobile_has_no_horizontal_overflow(ui):
    page, observed = ui
    plus_fixture(page)
    page.goto('http://ui.test/wechat-plus')
    expect(page.locator('[data-wp-input]')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert not observed['errors']


def test_copy_layout_keeps_html_styles_and_removes_executable_nodes(ui):
    page, _ = ui
    plus_fixture(page)
    page.add_init_script('''
      Object.defineProperty(window, 'ClipboardItem', {value:class {constructor(data){this.data=data;}}});
      Object.defineProperty(navigator, 'clipboard', {value:{write:async items => {
        window.copiedLayout = await items[0].data['text/html'].text();
      }}});
    ''')
    page.goto('http://ui.test/wechat-plus')
    page.locator('[data-wp-input]').fill('帮我选题')
    page.locator('[data-wp-send]').click()
    page.get_by_role('button', name='1. 会议结束后，怎样确认待办').click()
    expect(page.locator('[data-wp-editor]')).to_be_visible()
    page.locator('[data-wp-input]').fill('排版看看')
    page.locator('[data-wp-send]').click()
    button = page.locator('[data-wp-copy-html]')
    expect(button).to_be_enabled()
    button.click()
    expect(page.locator('[data-wp-save-state]')).to_contain_text('排版已复制')
    html = page.evaluate('window.copiedLayout')
    assert 'style="color:#214d3d"' in html
    assert '<h2>会议记录</h2>' in html
    assert '<script' not in html


def test_layout_guidance_and_theme_selection(ui):
    page, observed = ui
    plus_fixture(page)
    page.goto('http://ui.test/wechat-plus')
    page.locator('[data-wp-input]').fill('帮我选题')
    page.locator('[data-wp-send]').click()
    page.get_by_role('button', name='1. 会议结束后，怎样确认待办').click()
    expect(page.get_by_text('选择排版风格，或在下方描述你的想法')).to_be_visible()
    expect(page.locator('[data-wp-input]')).to_have_attribute('placeholder', '告诉我排版风格，例如：蓝色科技感、标题醒目…')
    page.get_by_role('button', name='简约清爽', exact=True).click()
    expect(page.locator('[data-wp-layout-theme]')).to_have_text('排版 · 简约清爽')
    expect(page.get_by_role('button', name='换一种排版')).to_be_visible()
    expect(page.locator('[data-wp-copy-html]')).to_be_enabled()
    assert not observed['errors']


def test_real_generated_layout_renders_in_plus_preview(ui):
    from pathlib import Path
    from unittest.mock import patch
    from server import wechat_plus_layout as layout, workbench
    page, observed = ui
    page.set_viewport_size({'width':1440,'height':1000})
    plus_fixture(page)
    with patch.object(workbench, 'SKILL_DIR', Path(__file__).resolve().parents[1] / 'vendor/skills/weChat-autoCreate'):
        html=layout.render('# 会议记录\n\n这是一篇测试文章。\n\n## 第一步\n\n核对任务和负责人。', dict(layout.THEMES['tech'],id='tech'))
    page.route(lambda url: '/api/wechat-plus/sessions/' in url and '/preview' in url,
               lambda route:route.fulfill(content_type='text/html; charset=utf-8',body=html))
    page.goto('http://ui.test/wechat-plus')
    page.locator('[data-wp-input]').fill('帮我选题')
    page.locator('[data-wp-send]').click()
    page.get_by_role('button', name='1. 会议结束后，怎样确认待办').click()
    page.get_by_role('button', name='简约清爽', exact=True).click()
    expect(page.locator('[data-wp-copy-html]')).to_be_enabled()
    page.get_by_role('tab', name='排版预览').click()
    frame=page.frame_locator('[data-wp-preview]')
    expect(frame.get_by_text('核对任务和负责人。')).to_be_visible()
    assert not observed['errors']


def test_layout_choices_work_on_phone(ui):
    page, observed = ui
    page.set_viewport_size({'width':390,'height':844})
    plus_fixture(page)
    page.goto('http://ui.test/wechat-plus')
    page.locator('[data-wp-input]').fill('帮我选题')
    page.locator('[data-wp-send]').click()
    page.get_by_role('button', name='1. 会议结束后，怎样确认待办').click()
    choice=page.get_by_role('button', name='简约清爽', exact=True)
    expect(choice).to_be_visible()
    assert choice.bounding_box()['height'] >= 44
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    choice.click()
    expect(page.locator('[data-wp-layout-theme]')).to_have_text('排版 · 简约清爽')
    assert not observed['errors']
