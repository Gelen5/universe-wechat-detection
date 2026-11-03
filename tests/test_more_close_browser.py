import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

@pytest.mark.parametrize('path',['/','/wechat-plus','/bookshelf','/market'])
def test_more_close_has_no_border_until_keyboard_focus(ui,path):
 page,_=ui
 page.set_viewport_size({'width':390,'height':844})
 page.goto('http://ui.test'+path)
 more=page.get_by_role('button',name='更多',exact=True)
 more.click()
 heading=page.locator('#shell-more-title')
 close=page.locator('#shell-more-menu > .shell-menu-close')
 expect(heading).to_be_focused()
 assert heading.evaluate('(e)=>getComputedStyle(e).outlineStyle==="none"')
 assert close.evaluate('(e)=>{const s=getComputedStyle(e);return s.borderStyle==="none" && s.boxShadow==="none" && !e.matches(":focus-visible")}')
 page.keyboard.press('Tab')
 expect(close).to_be_focused()
 assert close.evaluate('(e)=>e.matches(":focus-visible") && getComputedStyle(e).outlineStyle!=="none"')
 page.keyboard.press('Enter')
 expect(page.get_by_role('dialog',name='全部功能')).to_be_hidden()
 expect(more).to_be_focused()

@pytest.mark.parametrize('path',['/','/wechat-plus','/bookshelf','/market'])
def test_heading_never_shows_focus_outline_when_opened_with_keyboard(ui,path):
 page,_=ui
 page.set_viewport_size({'width':390,'height':844})
 page.goto('http://ui.test'+path)
 more=page.get_by_role('button',name='更多',exact=True)
 more.focus()
 page.keyboard.press('Enter')
 heading=page.locator('#shell-more-title')
 expect(heading).to_be_focused()
 assert heading.evaluate('(e)=>getComputedStyle(e).outlineStyle==="none"')
 page.keyboard.press('Tab')
 close=page.locator('#shell-more-menu > .shell-menu-close')
 expect(close).to_be_focused()
 assert close.evaluate('(e)=>getComputedStyle(e).outlineStyle!=="none"')
