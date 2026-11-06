from urllib.parse import urlparse, parse_qs
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

@pytest.mark.parametrize('width', [390,1440])
def test_board_paginates_and_retries(ui, width):
    page,_=ui
    page.set_viewport_size({'width':width,'height':900})
    offsets=[]
    def board(route):
        offset=int(parse_qs(urlparse(route.request.url).query).get('offset',['0'])[0])
        offsets.append(offset)
        if offset == 40 and offsets.count(40) == 1:
            route.fulfill(status=503, body='offline')
            return
        items=[{'title':f'item-{i}','art_url':'https://mp.weixin.qq.com/s/x','rank_no':i+1} for i in range(offset,min(offset+40,85))]
        route.fulfill(json={'items':items,'offset':offset,'has_more':offset+len(items)<85,'total':85,'counts':{'all':85},'categories':[],'dates':[]})
    page.route('**/api/image-board?*',board)
    page.goto('http://ui.test/image-board')
    expect(page.locator('#ib-grid .ib-card')).to_have_count(40)
    page.locator('[data-ib-more]').scroll_into_view_if_needed()
    expect(page.get_by_role('button',name='重试')).to_be_visible()
    page.get_by_role('button',name='重试').click()
    expect(page.locator('#ib-grid .ib-card')).to_have_count(80)
    page.locator('[data-ib-more]').scroll_into_view_if_needed()
    expect(page.locator('#ib-grid .ib-card')).to_have_count(85)
    expect(page.locator('[data-ib-more]')).to_have_count(0)
    assert offsets == [0,40,40,80]
