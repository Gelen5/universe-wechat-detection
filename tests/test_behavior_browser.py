import json
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser, ui

def test_real_shell_records_known_page_and_button_without_user_text(ui):
 page,_=ui
 observations=[]
 def receive(route):
  observations.append(json.loads(route.request.post_data))
  route.fulfill(status=204,body='')
 page.route('**/api/behavior',receive)
 page.goto('http://ui.test/viral-remix')
 expect(page.locator('#viral-remix-start')).to_be_visible()
 page.locator('#viral-remix-goal').fill('private content that must not be sent')
 page.locator('#viral-remix-start').click()
 page.wait_for_timeout(300)
 assert any(x['page']=='viral-remix' and x['event']=='page_view' for x in observations)
 assert any(x['event']=='remix_analyze' for x in observations)
 assert 'private content' not in str(observations)

def test_setting_entry_is_visible_only_to_owner(ui):
 page,_=ui
 page.route('**/api/auth/me',lambda r:r.fulfill(json={'user':{'id':'owner','email':'gelen5@163.com','role':'admin'},'wallet':{'balance':10}}))
 page.set_viewport_size({'width':1440,'height':900})
 page.goto('http://ui.test/')
 expect(page.locator('#owner-behavior-button')).to_be_attached()
 expect(page.locator('#owner-behavior-button')).not_to_have_attribute('hidden','')

def test_guest_visit_and_browse_choice_are_sent(ui):
 page,_=ui
 observations=[]
 page.route('**/api/auth/me',lambda r:r.fulfill(status=401,json={'detail':'请先登录'}))
 page.route('**/api/behavior',lambda r:(observations.append(json.loads(r.request.post_data)),r.fulfill(status=204,body='')))
 page.goto('http://ui.test/image-board',wait_until='networkidle')
 page.get_by_role('button',name='先逛逛，暂不登录').click()
 page.wait_for_timeout(200)
 assert any(x['page']=='image-board' and x['event']=='page_view' for x in observations)
 assert any(x['event']=='welcome_browse' for x in observations)
