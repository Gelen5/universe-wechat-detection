from copy import deepcopy
from unittest.mock import patch
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from server.main import app
from tests.test_ui_shell_browser import browser, ui
from tests.test_xhs_extract_browser import NOTE, PNG, extraction, submit

DY = {'id':'7699784646996823306','kind':'image','link':'https://www.douyin.com/video/7699784646996823306','title':'测试作品','desc':'测试正文','author':{'name':'作者'},'stats':{},'tags':[], 'images':[{'url':f'https://p3.douyinpic.com/{n}.jpg'} for n in range(2)]}

def test_douyin_gallery_click_zoom_and_video_download(ui):
    page, _ = ui
    state = {'note':deepcopy(DY)}
    page.route('**/api/douyin/extract', lambda r:r.fulfill(json={'note':state['note']}))
    page.route('**/api/douyin/media?*', lambda r:r.fulfill(content_type='image/png',body=PNG))
    page.goto('http://ui.test/douyin-extract')
    page.locator('#douyin-extract-url').fill('https://v.douyin.com/example/')
    page.locator('#douyin-extract-start').click()
    page.locator('[data-dy-zoom="0"]').click()
    dialog=page.locator('.dy-lightbox')
    expect(dialog).to_be_visible()
    page.keyboard.press('ArrowRight')
    expect(dialog.locator('[data-dy-count]')).to_have_text('2 / 2')
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    state['note'].update(kind='video',video={'url':'https://example.test/video.mp4'})
    page.locator('#douyin-extract-start').click()
    link=page.locator('.dy-video-download')
    expect(link).to_be_visible()
    assert 'download=1' in link.get_attribute('href')
    assert link.get_attribute('download') is not None
    page.route(lambda url: '/api/douyin/video?' in url and 'download=1' in url, lambda r:r.fulfill(content_type='video/mp4', body=b'\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom', headers={'Content-Type':'video/mp4','Content-Disposition':'attachment; filename=video.mp4'}))
    with page.expect_download() as download:
        link.click()
    assert 'download=1' in download.value.url
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

def test_xhs_video_download_and_cover_zoom(ui):
    page,_=ui
    state=extraction(page)
    state['note'].update(kind='video',cover=NOTE['images'][0],video={'url':'https://sns-video.xhscdn.com/test.mp4'})
    page.goto('http://ui.test/xhs-extract')
    submit(page)
    link=page.locator('.xe-video-download')
    expect(link).to_be_visible()
    assert 'download=1' in link.get_attribute('href')
    page.locator('.xe-cover img').click()
    expect(page.locator('#xhs-extract-lightbox')).to_be_visible()

def test_video_download_responses_have_attachment_headers():
    client=TestClient(app)
    assert client.post('/api/auth/login', json={'email':'admin@example.com','password':'testing-pass-123'}).status_code == 200
    url='https://sns-video.xhscdn.com/test.mp4'
    with patch('server.xhs_extract.cached_media',return_value=None), patch('server.xhs_extract.download_media',return_value=(b'video', 'video/mp4')), patch('server.xhs_extract.store_media'):
        r=client.get('/api/xhs/media',params={'url':url,'download':'1'})
        assert r.status_code == 200 and r.content == b'video'
        assert r.headers['content-disposition'].startswith('attachment;')
    with patch('server.douyin_extract._signed_request',return_value={}), patch('server.douyin_extract.pick_video',return_value={'url':'https://p3.douyinpic.com/video.mp4'}), patch('server.douyin_extract._stream_video',return_value=iter([b'video'])):
        r=client.get('/api/douyin/video',params={'id':DY['id'],'download':'1'})
        assert r.status_code == 200 and r.content == b'video'
        assert r.headers['content-disposition'] == 'attachment; filename="douyin-7699784646996823306.mp4"'

def test_result_layout_on_mobile_keeps_media_and_actions_usable(ui):
    page, _ = ui
    page.set_viewport_size({'width': 375, 'height': 812})
    extraction(page)
    page.goto('http://ui.test/xhs-extract')
    submit(page)
    expect(page.locator('.extract-result-heading')).to_be_visible()
    assert page.locator('.xe-document').bounding_box()['y'] > page.locator('.xe-media').bounding_box()['y']
    page.locator('.xe-main-image').click()
    expect(page.locator('#xhs-extract-lightbox')).to_be_visible()
    page.keyboard.press('Escape')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.route('**/api/douyin/extract', lambda r:r.fulfill(json={'note':DY}))
    page.route('**/api/douyin/media?*', lambda r:r.fulfill(content_type='image/png',body=PNG))
    page.goto('http://ui.test/douyin-extract')
    page.locator('#douyin-extract-url').fill('https://v.douyin.com/example/')
    page.locator('#douyin-extract-start').click()
    expect(page.locator('.extract-result-heading')).to_be_visible()
    assert page.locator('.dy-details').bounding_box()['y'] > page.locator('.dy-media-card').bounding_box()['y']
    page.locator('[data-dy-zoom="0"]').click()
    expect(page.locator('.dy-lightbox')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

def test_link_composers_are_accessible_and_fit_desktop_and_mobile(ui):
    page, _ = ui
    for width in (390, 1440):
        page.set_viewport_size({'width': width, 'height': 900})
        for path, field, button in [('xhs-extract', '#xhs-extract-url', '#xhs-extract-start'), ('douyin-extract', '#douyin-extract-url', '#douyin-extract-start')]:
            page.goto('http://ui.test/' + path)
            page.locator(field).fill('https://example.com/shared-content')
            expect(page.locator(field)).to_have_value('https://example.com/shared-content')
            box = page.locator(button).bounding_box()
            input_box = page.locator(field).bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width
            assert box['width'] >= 100 and box['height'] >= 44
            if width > 560:
                assert box['x'] >= input_box['x'] + input_box['width'] - 1
                assert box['width'] <= 160
            else:
                assert box['y'] >= input_box['y'] + input_box['height'] - 1
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
