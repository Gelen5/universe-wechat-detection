from tests.test_ui_shell_browser import browser, ui
from playwright.sync_api import expect
import pytest
@pytest.mark.parametrize('width',[1440,390,320])
def test_home_stage(ui,width):
 page,_=ui
 page.set_viewport_size({'width':width,'height':900})
 page.goto('http://ui.test/')
 h=page.locator('#home .he-intro h1')
 assert h.inner_text().replace(chr(10),'').startswith('宇宙第一工作台')
 box=h.bounding_box()
 assert box['x']>=0 and box['x']+box['width']<=width
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 assert h.evaluate('(el) => el.scrollWidth <= el.clientWidth')
 assert page.locator('#home .he-writing').get_attribute('href')=='/wechat-plus'
 assert page.locator('#home .he-grid a[href="/viral-remix"]').get_attribute('href')=='/viral-remix'
 assert page.locator('#home .he-visual').get_attribute('href')=='/article-visual'
 page.screenshot(path=f'D:/Download/workbench-audit-20261027/home-refine-{width}.png',full_page=True)
