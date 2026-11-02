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
