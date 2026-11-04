import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui


@pytest.mark.parametrize('width', [390, 1440])
def test_board_prefills_selected_article_without_starting_extraction(ui, width):
    page, state = ui
    page.set_viewport_size({'width': width, 'height': 900})
    urls = ['https://mp.weixin.qq.com/s/first', 'https://mp.weixin.qq.com/s/second']
    items = [{'title': '文章' + str(i), 'art_url': url, 'cover_url': '', 'image_num': 1} for i, url in enumerate(urls)]
    page.route('**/api/image-board?*', lambda route: route.fulfill(json={'items': items, 'total': 2, 'counts': {'all': 2}, 'categories': [], 'dates': []}))
    requests = []
    def extract(route):
        requests.append(route.request.post_data_json)
        route.fulfill(json={'title': '文章一', 'token': 'abc', 'images': [{'url': '/api/sticker-extract/abc/1', 'index': 1}]})
    page.route('**/api/sticker-extract', extract)
    page.goto('http://ui.test/image-board')
    expect(page.locator('[data-ib-extract]')).to_have_count(2)
    page.locator('[data-ib-extract]').nth(1).click()
    expect(page.locator('#sticker-extract')).to_be_visible()
    assert requests == []
    expect(page.locator('#sticker-start')).to_be_visible()
    page.locator('#sticker-start').click()
    expect(page.locator('#sticker-result')).to_be_visible()
    assert requests == [{'url': urls[1]}]
    expect(page.locator('[data-sticker-remix]')).to_be_visible()
    assert page.locator('#sticker-url').input_value() == urls[1]
