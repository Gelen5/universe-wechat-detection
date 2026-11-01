from tests.test_ui_shell_browser import browser,ui
import pytest
@pytest.mark.parametrize('width',[1440,390,320])
def test_editorial(ui,width):
 p,_=ui;p.set_viewport_size({'width':width,'height':900});p.goto('http://ui.test/')
 assert p.locator('.home-editorial h1').inner_text().replace(chr(10),'')=='宇宙第一工作台.'
 assert p.locator('.he-feature[href="/article-visual"]').count()==1
 assert '爆文转贴图' in p.locator('.he-feature[href="/article-visual"]').inner_text()
 assert p.locator('.home-editorial a[href="/one-click-writing"]').count()==0
 assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
 p.screenshot(path=f'D:/Download/workbench-audit-20261027/home-editorial-{width}.png',full_page=True)

