"""Reading-wall density, navigation and delegated hotspot actions; no model calls."""
from urllib.parse import urlparse,parse_qs
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser,ui,ROOT

PLATFORMS=[('weibo','微博'),('zhihu','知乎'),('douyin','抖音'),('toutiao','今日头条'),('baidu','百度'),('bilibili','B站'),('juejin','掘金'),('tieba','贴吧'),('douban','豆瓣'),('v2ex','V2EX'),('hackernews','Hacker News'),('github','GitHub Trending')]


def hotspots_fixture(page):
    items=[{'platform':pid,'platform_zh':name,'title':f'{name}热点{i}：如何从真实问题出发，找到值得分享的内容方向','url':f'https://example.com/{pid}/{i}','rank':i,'hot':f'{10000-i} 热度'} for pid,name in PLATFORMS for i in range(1,13)]
    calls=[]
    def serve(route):
        parsed=urlparse(route.request.url);q=parse_qs(parsed.query);calls.append((parsed.path,q,route.request.method))
        if parsed.path.endswith('/refresh'):
            route.fulfill(json={'status':'ok'});return
        rows=[r for r in items if (not q.get('platform') or r['platform']==q['platform'][0]) and (not q.get('q') or q['q'][0] in r['title'])]
        route.fulfill(json={'items':rows,'platforms':[{'id':pid,'name':name,'count':12,'ok':True} for pid,name in PLATFORMS],'updated_at':'2026-10-25T06:00:00Z','degraded':False})
    page.route('**/api/hotspots**',serve)
    return calls


@pytest.mark.parametrize('width,columns',[(390,1),(1280,2),(1440,3),(1920,4),(2560,6)])
def test_hotspots_wall_shows_many_platforms_without_small_text(ui,width,columns):
    page,_=ui;page.set_viewport_size({'width':width,'height':1159});hotspots_fixture(page)
    page.goto('http://ui.test/hotspots')
    expect(page.locator('.hs-card')).to_have_count(12)
    assert len(page.locator('#hs-grid').evaluate('e=>getComputedStyle(e).gridTemplateColumns.split(" ")'))==columns
    assert page.locator('.hs-card').evaluate_all('els=>new Set(els.map(e=>getComputedStyle(e).backgroundColor)).size===12')
    assert page.locator('.hs-card-list').evaluate_all('els=>els.every(e=>e.children.length===4)')
    assert float(page.locator('.hs-item-title').first.evaluate('e=>parseFloat(getComputedStyle(e).fontSize)'))>=15
    assert page.locator('.hs-card').evaluate_all('els=>els.every(e=>e.scrollWidth<=e.clientWidth+1)')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    active=page.locator('.app-tabs [data-view="hotspots"]')
    expect(active).to_have_class('active');expect(active).to_have_attribute('aria-current','page')
    expect(page.locator('.app-tabs a.active')).to_have_count(1)
    if width==2560:
        assert page.locator('.hs-card-head').evaluate_all('els=>els.every(e=>e.getBoundingClientRect().bottom<=innerHeight)')
        page.screenshot(path=str(ROOT/'output/mint-ui/hotspots-wall-wide.png'))
    if width==1440:page.screenshot(path=str(ROOT/'output/mint-ui/hotspots-wall-1440.png'))


def test_hotspots_navigation_survives_switch_reload_and_more_menu(ui):
    page,_=ui;page.set_viewport_size({'width':1440,'height':1000});hotspots_fixture(page)
    page.goto('http://ui.test/workbench')
    page.locator('.app-tabs [data-view="hotspots"]').click()
    expect(page).to_have_url('http://ui.test/hotspots')
    expect(page.locator('#hotspots')).to_be_visible()
    expect(page.locator('.app-tabs [data-view="hotspots"]')).to_have_attribute('aria-current','page')
    page.reload()
    expect(page.locator('.app-tabs [data-view="hotspots"]')).to_have_class('active')
    page.locator('.app-tabs [data-view="workbench"]').click()
    expect(page.locator('body')).not_to_have_class('atelier hotspots-body')
    expect(page.locator('.app-tabs [data-view="hotspots"]')).not_to_have_attribute('aria-current','page')
    page.set_viewport_size({'width':390,'height':844})
    page.get_by_role('button',name='更多',exact=True).click()
    page.get_by_role('navigation',name='全部功能').get_by_role('link',name='热点广场',exact=True).click()
    expect(page.locator('#hotspots')).to_be_visible()
    page.get_by_role('button',name='更多',exact=True).click()
    expect(page.get_by_role('navigation',name='全部功能').get_by_role('link',name='热点广场',exact=True)).to_have_attribute('aria-current','page')


def test_hotspot_filters_rotation_refresh_favorite_and_creation_preserve_data(ui):
    page,_=ui;page.set_viewport_size({'width':1920,'height':1159});calls=hotspots_fixture(page)
    page.goto('http://ui.test/hotspots')
    card=page.locator('.hs-card[data-platform="weibo"]')
    expect(card.locator('.hs-item-title').first).to_contain_text('微博热点1：')
    card.locator('[data-rotate]').click();expect(card.locator('.hs-item-title').first).to_contain_text('微博热点5：')
    card.locator('[data-refresh]').click()
    expect(card.locator('[data-refresh]')).to_be_enabled()
    assert any(path.endswith('/refresh') and q.get('platform')==['weibo'] and method=='POST' for path,q,method in calls)
    page.evaluate("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async text=>{window.__copiedHotspot=text;}}})")
    title=card.locator('.hs-item-title').first.inner_text()
    card.locator('[data-copy]').first.click()
    expect(card.locator('[data-copy]').first).to_have_text('已复制')
    assert page.evaluate('window.__copiedHotspot')==title
    fav=card.locator('[data-fav]').first;fav.click();expect(fav).to_have_attribute('aria-pressed','true')
    page.locator('[data-fav-view]').click();expect(page.locator('.hs-card h2')).to_have_text('我的收藏')
    expect(page.locator('.hs-item-title')).to_have_count(1)
    page.reload();expect(page.locator('[data-fav-view]')).to_contain_text('1')
    page.locator('[data-open-platform="weibo"]').click();expect(page.locator('.hs-card')).to_have_count(1)
    expect(page.locator('.hs-item-title')).to_have_count(12)
    page.locator('#hs-search').fill('完全找不到的词');expect(page.locator('.hs-empty')).to_be_visible()
    page.locator('#hs-search').fill('');expect(page.locator('.hs-item-title')).to_have_count(12)
    page.locator('.hs-go').first.click()
    expect(page.locator('#workbench')).to_be_visible()
    expect(page.locator('#workbench-topic')).to_have_value('围绕这个热点写一篇公众号：微博热点1：如何从真实问题出发，找到值得分享的内容方向（来源：https://example.com/weibo/1）')
    # Existing document capture handlers may intercept programmatic send clicks;
    # the UI contract here is source-preserving handoff to the writing composer.


def test_hotspots_failed_load_can_be_retried_without_losing_navigation(ui):
    page,_=ui;page.set_viewport_size({'width':1440,'height':1000});hotspots_fixture(page)
    first=[True]
    def fail_once(route):
        if first[0]:first[0]=False;route.fulfill(status=503,json={'detail':'test failure'})
        else:route.fallback()
    page.route('**/api/hotspots**',fail_once)
    page.goto('http://ui.test/hotspots')
    expect(page.locator('.hs-empty')).to_contain_text('热榜暂时读不到')
    page.get_by_role('button',name='重新加载',exact=True).click()
    expect(page.locator('.hs-card')).to_have_count(12)
    expect(page.locator('.app-tabs [data-view="hotspots"]')).to_have_attribute('aria-current','page')


def test_platform_counts_and_chips_remain_stable_without_loading_flash(ui):
    page,_=ui;page.set_viewport_size({'width':1920,'height':1159});calls=hotspots_fixture(page)
    page.goto('http://ui.test/hotspots')
    expect(page.locator('.hs-card')).to_have_count(12)
    all_chip=page.locator('#hs-platforms [data-platform=""]')
    expect(all_chip).to_have_text('全部 144')
    page.evaluate("""() => {
      window.originalHotspotChip=document.querySelector('#hs-platforms [data-platform=""]');
      window.hotspotLoadingFrames=0;
      new MutationObserver(records=>{
        for(const record of records) for(const node of record.addedNodes)
          if(node.nodeType===1 && (node.matches('.hs-skeleton') || node.querySelector('.hs-skeleton'))) window.hotspotLoadingFrames++;
      }).observe(document.querySelector('#hs-grid'),{childList:true,subtree:true});
    }""")
    initial_requests=len(calls)
    for platform in ['weibo','zhihu','douyin','']:
        page.locator(f'#hs-platforms [data-platform="{platform}"]').click()
        expect(page.locator('.hs-card')).to_have_count(1 if platform else 12)
        expect(all_chip).to_have_text('全部 144')
        expect(page.locator('#hs-platforms .hs-chip-count')).to_have_count(13)
        assert page.evaluate('window.originalHotspotChip===document.querySelector(\'#hs-platforms [data-platform=""]\')')
    page.locator('#hs-search').fill('知乎热点1：')
    expect(page.locator('.hs-item-title')).to_have_count(1)
    expect(all_chip).to_have_text('全部 144')
    page.locator('#hs-search').fill('')
    expect(page.locator('.hs-card')).to_have_count(12)
    assert len(calls)==initial_requests
    assert page.evaluate('window.hotspotLoadingFrames')==0


def test_failed_refresh_keeps_existing_hotspots_and_counts(ui):
    page,_=ui;page.set_viewport_size({'width':1440,'height':1000});hotspots_fixture(page)
    page.goto('http://ui.test/hotspots')
    expect(page.locator('.hs-card')).to_have_count(12)
    page.route('**/api/hotspots?**',lambda route: route.fulfill(status=503,json={'detail':'temporary failure'}))
    page.locator('[data-refresh="weibo"]').click()
    expect(page.locator('#hs-banner')).to_contain_text('已保留当前热点')
    expect(page.locator('.hs-card')).to_have_count(12)
    expect(page.locator('#hs-platforms [data-platform=""]')).to_have_text('全部 144')
    expect(page.locator('.hs-skeleton')).to_have_count(0)
    expect(page.locator('#hs-grid')).to_have_attribute('aria-busy','false')
