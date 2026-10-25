"""Resource presentation and real controls against isolated catalog fixtures."""
from urllib.parse import urlparse, parse_qs
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui, ROOT


def market_fixture(page):
    rows = [
        {'id':'writing','name':'Writing Tools','name_zh':'写作与排版工具','description_zh':'整理文章结构、检查标题与段落，再将文稿交接给排版流程。','repo':'example/writing-tools','path':'skills/writing','url':'https://github.com/example/writing-tools','category':'productivity','category_zh':'效率','stars':1200,'added_at':'2026-10-20'},
        {'id':'code','name':'Code Review','name_zh':'代码审查助手','description_zh':'检查代码变更中的问题，整理可执行的修改建议。','repo':'example/code-review','path':'','url':'https://github.com/example/code-review','category':'coding','category_zh':'编程','stars':800,'added_at':'2026-10-21'},
        {'id':'research','name':'Research Notes','name_zh':'研究资料整理','description_zh':'整理公开来源、提取资料要点，并保留原始出处。','repo':'example/research-notes','path':'','url':'https://github.com/example/research-notes','category':'science','category_zh':'科研','stars':400,'added_at':'2026-10-22'},
    ]
    calls=[]
    def serve(route):
        parsed=urlparse(route.request.url); query=parse_qs(parsed.query);calls.append(query)
        if parsed.path.endswith('/meta'):
            route.fulfill(json={'count':3,'repos':3,'official':0,'generated_at':'2026-10-25T00:00:00Z','categories':[{'slug':'productivity','name':'效率','count':1},{'slug':'coding','name':'编程','count':1},{'slug':'science','name':'科研','count':1}]});return
        if query.get('featured')==['true']:
            route.fulfill(json={'items':[dict(rows[0],featured=True)]});return
        result=[r for r in rows if (not query.get('category') or r['category']==query['category'][0]) and (not query.get('q') or query['q'][0] in r['name_zh'])]
        if query.get('sort')==['added']: result=list(reversed(result))
        page_number=int(query.get('page',['1'])[0]);total=len(result)
        route.fulfill(json={'items':result[(page_number-1)*2:page_number*2],'total':total,'pages':(total+1)//2})
    page.route('**/api/market/**',serve)
    return calls


@pytest.mark.parametrize('width,columns',[(390,2),(768,3),(1280,4),(1440,4),(2560,5)])
def test_library_has_readable_covers_and_content_based_columns(ui,width,columns):
    page,_=ui;page.set_viewport_size({'width':width,'height':1000});page.goto('http://ui.test/bookshelf')
    expect(page.locator('.book-link')).to_have_count(21)
    assert len(page.locator('#book-grid').evaluate('e=>getComputedStyle(e).gridTemplateColumns.split(" ")'))==columns
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert page.locator('.book-cover').evaluate_all('els=>els.every(e=>e.scrollHeight<=e.clientHeight+1 && e.scrollWidth<=e.clientWidth+1)')
    assert float(page.locator('.book-meta h3').first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)'))>=14
    if width==1440:page.screenshot(path=str(ROOT/'output/mint-ui/library-editorial-1440.png'))


@pytest.mark.parametrize('width',[390,768,1280,1440,2560])
def test_market_grid_preserves_filter_search_sort_and_source_links(ui,width):
    page,_=ui;page.set_viewport_size({'width':width,'height':1000});calls=market_fixture(page)
    page.goto('http://ui.test/market')
    expect(page.locator('.market-row')).to_have_count(2)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert float(page.locator('.market-row .name').first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)'))>=16
    expect(page.locator('.market-row').first).to_contain_text('前往 GitHub')
    assert page.locator('.market-row').first.get_attribute('href')=='https://github.com/example/writing-tools'
    assert page.locator('.market-row').first.get_attribute('target')=='_blank'
    if width==1440:page.screenshot(path=str(ROOT/'output/mint-ui/market-editorial-1440.png'))
    page.locator('#market-more button').click();expect(page.locator('.market-row')).to_have_count(3)
    page.locator('#market-categories [data-category="coding"]').click();expect(page.locator('.market-row')).to_have_count(1)
    expect(page.locator('.market-row')).to_contain_text('代码审查助手')
    page.locator('#market-categories [data-category=""]').click();expect(page.locator('.market-row')).to_have_count(2)
    page.locator('#market-search-input').fill('研究');expect(page.locator('.market-row')).to_have_count(1)
    expect(page.locator('.market-row')).to_contain_text('研究资料整理')
    page.locator('#market-search-input').fill('找不到的工具');expect(page.locator('.market-empty')).to_be_visible()
    page.locator('#market-search-input').fill('');expect(page.locator('.market-row')).to_have_count(2)
    page.locator('#market-sort [data-sort="added"]').click()
    expect(page.locator('.market-row').first).to_contain_text('研究资料整理')
    assert any(c.get('sort')==['added'] for c in calls)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def test_market_uses_the_same_presentation_inside_workbench_tabs(ui):
    page,_=ui;page.set_viewport_size({'width':1440,'height':1000});market_fixture(page)
    page.goto('http://ui.test/workbench')
    page.locator('.app-tabs [data-view="market"]').click()
    expect(page.locator('#market')).to_be_visible()
    host=page.locator('#market').bounding_box();content=page.locator('#market-main').bounding_box()
    assert abs(host['x']-content['x'])<1
    assert abs(host['width']-content['width'])<1
    expect(page.locator('.market-row')).to_have_count(2)
    assert page.locator('#market-list').evaluate('e=>getComputedStyle(e).display')=='grid'
    assert float(page.locator('.market-row .name').first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)'))>=16
    page.locator('.app-tabs [data-view="workbench"]').click()
    expect(page.locator('#workbench')).to_be_visible()
    expect(page.locator('#market')).to_be_hidden()


@pytest.mark.parametrize('width',[390,1440,2560])
def test_resource_header_panels_align_with_content_and_keep_search_usable(ui,width):
    page,_=ui;page.set_viewport_size({'width':width,'height':1000});market_fixture(page)
    page.goto('http://ui.test/bookshelf')
    expect(page.locator('.book-link')).to_have_count(21)
    panel=page.locator('.library-heading')
    assert panel.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(238, 243, 232)'
    box=panel.bounding_box();grid=page.locator('#book-grid').bounding_box()
    assert abs(box['x']-grid['x'])<1 and abs(box['width']-grid['width'])<1
    search=page.locator('#search-toggle').bounding_box()
    assert search['x']>=box['x'] and search['x']+search['width']<=box['x']+box['width']
    page.get_by_role('button',name='搜索书名',exact=True).click()
    expect(page.locator('#book-search')).to_be_visible()
    page.goto('http://ui.test/market')
    expect(page.locator('.market-row')).to_have_count(2)
    panel=page.locator('.market-hero > .market-wrap');box=panel.bounding_box();search=page.locator('.market-search').bounding_box()
    assert panel.evaluate('e=>getComputedStyle(e).backgroundColor')=='rgb(234, 242, 237)'
    assert abs(box['x']-search['x'])<1 and abs(box['width']-search['width'])<1
    assert search['y']-box['y']-box['height']>=23
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    if width==1440:page.screenshot(path=str(ROOT/'output/mint-ui/market-header-panel-1440.png'))
