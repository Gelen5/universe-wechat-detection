from pathlib import Path
from urllib.parse import urlparse
import mimetypes
import pytest
from playwright.sync_api import expect
from tests.test_ui_shell_browser import browser
ROOT=Path(__file__).resolve().parents[1]
@pytest.mark.parametrize('width',[1440,390])
def test_revenue_page(browser,width):
 p=browser.new_page(viewport={'width':width,'height':900}); errors=[];p.on('pageerror',lambda e:errors.append(str(e)))
 def serve(route):
  url=urlparse(route.request.url)
  if url.path=='/api/owner-revenue':
   route.fulfill(json={'lifetime_net':'79.80','lifetime_paid':'99.00','lifetime_refunded':'19.20','today_paid':'99.00','period_paid':'99.00','period_count':1,'missing_paid_time':0,'daily':[{'date':'2026-11-01','amount':'99.00','count':1}],'packages':[{'name':'创作包','amount':'99.00','count':1}],'orders':[{'out_trade_no':'fixture','subject':'创作包','email':'demo@example.test','status':'PARTIAL_REFUNDED','paid_at':'2026-11-01 12:00:00','total_amount':'99.00','refunded_amount':'19.20'}],'total_orders':1,'start':'2026-11-01','end':'2026-11-01','updated_at':'2026-11-01T12:00:00+08:00'})
  else:
   f=ROOT/'static'/('owner-revenue.html' if url.path=='/owner-revenue' else Path(url.path).name)
   route.fulfill(body=f.read_bytes(),content_type=mimetypes.guess_type(str(f))[0] or 'text/plain')
 p.route('**/*',serve);p.goto('http://ui.test/owner-revenue')
 expect(p.locator('#cards')).to_contain_text('79.80')
 expect(p.locator('#cards')).to_contain_text('今日支付收入')
 assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
 p.get_by_role('button',name='查看',exact=True).click()
 expect(p.locator('#detail')).to_contain_text('19.20')
 expect(p.locator('#detail')).to_contain_text('暂无逐笔记录')
 p.keyboard.press('Escape');expect(p.locator('#detail')).not_to_be_visible()
 p.screenshot(path=f'D:/Download/workbench-audit-20261027/owner-revenue-{width}.png',full_page=True)
 assert not errors;p.close()
