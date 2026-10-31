"""Real browser interactions with bounded extraction/media fixtures, no paid calls."""
from copy import deepcopy
import base64

from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jVZkAAAAASUVORK5CYII=')
NOTE = {'id':'test-note','kind':'image','link':'https://www.xiaohongshu.com/explore/test-note',
    'title':'提取结果标题','desc':'第一段正文。\n\n第二段正文。','author':{'name':'作者'},
    'stats':{'liked':100,'collected':-1,'comment':0,'share':3},'published':'2026-10-31',
    'tags':['记录','创作'],'images':[{'url':f'https://sns-webpic-qc.xhscdn.com/{n}.png'} for n in range(3)]}


def extraction(page):
    state = {'note':deepcopy(NOTE), 'fail':False, 'requests':0}
    def handle(route):
        state['requests'] += 1
        if state['fail']:
            route.fulfill(status=400, json={'detail':'请重新复制完整分享链接'})
        else:
            route.fulfill(json={'note':state['note']})
    page.route('**/api/xhs/extract', handle)
    page.route('**/api/xhs/media?*', lambda route:route.fulfill(content_type='image/png', body=PNG))
    page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copiedText=text;}}});")
    return state


def submit(page):
    page.locator('#xhs-extract-url').fill('https://www.xiaohongshu.com/explore/test-note?xsec_token=test')
    page.locator('#xhs-extract-start').click()
    expect(page.locator('#xhs-extract-result')).to_be_visible()


def test_gallery_copy_zoom_download_and_failure_preserves_result(ui):
    page, observed = ui
    page.set_viewport_size({'width':1440,'height':1000})
    state = extraction(page)
    page.goto('http://ui.test/xhs-extract')
    submit(page)
    expect(page.locator('.xe-result-head h2')).to_have_text(NOTE['title'])
    expect(page.locator('.xe-stats div').nth(1).locator('dd')).to_have_text('—')
    expect(page.locator('.xe-stats div').nth(2).locator('dd')).to_have_text('0')
    page.locator('[data-xe-image="1"] img').click()
    expect(page.locator('[data-xe-index]')).to_have_text('第 2 / 3 张')
    expect(page.locator('.xe-main-image')).to_have_css('object-fit','contain')
    page.locator('button[data-xe-zoom]').click()
    dialog = page.locator('#xhs-extract-lightbox')
    expect(dialog).to_be_visible()
    page.keyboard.press('ArrowRight')
    expect(page.locator('[data-xe-lightbox-index]')).to_have_text('3 / 3')
    with page.expect_download() as download:
        dialog.locator('[data-xe-download]').click()
    assert download.value.suggested_filename == 'xiaohongshu-test-note-3.png'
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    page.locator('[data-copy="bundle"]').click()
    page.wait_for_function("window.copiedText?.includes('来源：')")
    assert NOTE['desc'] in page.evaluate('window.copiedText')
    state['fail'] = True
    page.locator('#xhs-extract-start').click()
    expect(page.locator('#xhs-extract-error')).to_contain_text('重新复制完整分享链接')
    expect(page.locator('.xe-result-head h2')).to_have_text(NOTE['title'])
    expect(page.locator('#xhs-extract-url')).not_to_have_value('')
    assert state['requests'] == 2
    assert not observed['errors']


def test_video_only_renders_player_when_video_url_exists(ui):
    page, _ = ui
    state = extraction(page)
    state['note'].update(kind='video',cover=NOTE['images'][0],imageCount=0,video=None)
    page.goto('http://ui.test/xhs-extract')
    submit(page)
    expect(page.locator('video')).to_have_count(0)
    expect(page.locator('.xe-media-note')).to_contain_text('暂未返回可播放地址')
    expect(page.locator('.xe-badges')).to_contain_text('视频作品')
    expect(page.locator('.xe-thumbs')).to_have_count(0)
    state['note']['video'] = {'url':'https://sns-video.xhscdn.com/test.mp4','width':1080,'height':1920}
    page.locator('#xhs-extract-start').click()
    expect(page.locator('video.xe-video')).to_have_count(1)
    expect(page.locator('.xe-cover')).to_be_visible()
    expect(page.locator('.xe-main-image')).to_have_count(0)


def test_wait_timer_duplicate_guard_and_mobile_layout(ui):
    page, _ = ui
    extraction(page)
    held = []
    page.route('**/api/xhs/extract', lambda route:held.append(route))
    page.goto('http://ui.test/xhs-extract')
    page.locator('#xhs-extract-url').fill('test share')
    page.locator('#xhs-extract-start').click()
    expect(page.locator('#xhs-extract-progress')).to_be_visible()
    expect(page.locator('#xhs-extract-start')).to_be_disabled()
    page.locator('#xhs-extract-url').press('Control+Enter')
    page.wait_for_function("document.querySelector('#xhs-extract-progress-text').textContent.includes('已等待 1 秒')")
    assert len(held) == 1
    held[0].fulfill(json={'note':NOTE})
    expect(page.locator('#xhs-extract-progress')).to_be_hidden()
    media = page.locator('.xe-media').bounding_box()
    text = page.locator('.xe-document').bounding_box()
    assert text['y'] >= media['y'] + media['height'] - 1
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('button[data-xe-zoom]').click()
    modal = page.locator('#xhs-extract-lightbox')
    expect(modal).to_be_visible()
    box = modal.bounding_box()
    assert box['x'] >= 0 and box['x'] + box['width'] <= 391
    expect(modal.locator('[data-xe-download]')).to_have_css('min-height','44px')
    page.keyboard.press('Escape')


def test_account_switch_clears_results_and_link(ui):
    page, _ = ui
    extraction(page)
    page.goto('http://ui.test/xhs-extract')
    submit(page)
    page.evaluate("currentAccount={id:'another-user'}; window.dispatchEvent(new Event('account-changed'))")
    expect(page.locator('#xhs-extract-result')).to_be_hidden()
    expect(page.locator('#xhs-extract-url')).to_have_value('')
    expect(page.locator('#xhs-extract-empty')).to_be_visible()
