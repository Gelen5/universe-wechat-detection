from pathlib import Path
import json,time
from playwright.sync_api import sync_playwright,expect
root=Path(__file__).resolve().parents[1];out=root/'output'/'qihaoshou-qa';out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(channel='msedge',headless=True)
 context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True,permissions=['clipboard-read','clipboard-write'])
 page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('dialog',lambda d:d.accept())
 page.goto('http://127.0.0.1:8894/qihaoshou');page.locator('#q-email').fill('writer-test@example.com');page.locator('#q-password').fill('writer-test-123');page.locator('#q-login-form button').click()
 expect(page.locator('#q-studio')).to_be_visible()
 page.locator('#q-topic').fill('如何把每天的记录整理成文章')
 page.locator('#q-generate').click()
 expect(page.locator('#q-stream')).to_contain_text('从一段记录',timeout=15000)
 expect(page.locator('#q-status')).to_contain_text('文章已生成并保存',timeout=20000)
 editor=page.frame_locator('#q-editor');expect(editor.locator('h1')).to_have_text('从一段记录开始写作')
 page.locator('#q-theme').select_option('blue');page.locator('#q-layout').click();expect(page.locator('#q-status')).to_contain_text('主题已应用')
 expect(editor.locator('h2')).to_have_attribute('style',__import__('re').compile('2563a7'))
 page.locator('#q-titles').click();expect(page.locator('#q-title-list button')).to_have_count(3,timeout=15000)
 page.locator('#q-title-list button').nth(1).click();expect(page.locator('#q-title')).to_have_value('把素材整理成自己的文章')
 page.locator('#q-deai').click();expect(page.locator('#q-status')).to_contain_text('深度改稿通过',timeout=15000)
 page.locator('#q-deai-review summary').click();expect(page.locator('#q-deai-changes')).to_contain_text('改前：')
 page.locator('#q-deai-undo').click();expect(page.locator('#q-status')).to_contain_text('已恢复改写前')
 expect(editor.locator('p').first).to_contain_text('先记录今天发生的事情')
 page.locator('#q-image-prompt').fill('阳光下的书桌与笔记本');page.locator('#q-image').click();expect(editor.locator('img')).to_have_count(1,timeout=15000)
 expect(page.locator('#q-status')).to_contain_text('配图已插入',timeout=15000)
 page.locator('#q-copy').click();expect(page.locator('#q-status')).to_contain_text('文字格式已复制',timeout=10000)
 clip=page.evaluate('navigator.clipboard.readText()');assert '记录' in clip
 with page.expect_download() as download:
  page.locator('#q-export').click()
 exported=out/'exported.html';download.value.save_as(str(exported));assert 'data:image/jpeg;base64,' in exported.read_text('utf-8')
 page.locator('#q-publish').click();expect(page.locator('#q-status')).to_contain_text('fixture-draft',timeout=10000)
 # Cancel a second real HTTP stream and confirm reservation is refunded.
 before=page.request.get('http://127.0.0.1:8894/api/wallet').json()['wallet']['balance']
 prior=editor.locator('body').inner_html()
 page.locator('#q-generate').click()
 expect(page.locator('#q-stop')).to_be_visible(timeout=15000)
 expect(page.locator('#q-stream')).to_contain_text('从一段记录',timeout=15000)
 page.locator('#q-stop').click()
 expect(page.locator('#q-status')).to_contain_text('停止请求已发送',timeout=10000)
 for _ in range(50):
  if page.request.get('http://127.0.0.1:8894/api/wallet').json()['wallet']['balance']==before:break
  time.sleep(.1)
 else:raise AssertionError('cancelled generation did not refund')
 assert editor.locator('body').inner_html()==prior
 page.screenshot(path=str(out/'desktop.png'),full_page=True)
 history=page.locator('#q-history').input_value();page.reload();expect(page.locator('#q-studio')).to_be_visible();page.locator('#q-history').select_option(history);expect(editor.locator('img')).to_have_count(1)
 mobile=context.new_page();mobile.set_viewport_size({'width':390,'height':844});mobile.goto('http://127.0.0.1:8894/qihaoshou');expect(mobile.locator('#q-studio')).to_be_visible();mobile.locator('#q-history').select_option(history);expect(mobile.frame_locator('#q-editor').locator('h1')).to_have_text('把素材整理成自己的文章')
 assert mobile.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'mobile horizontal overflow'
 mobile.screenshot(path=str(out/'mobile.png'),full_page=True)
 assert not errors,errors
 (out/'result.json').write_text(json.dumps({'status':'passed','browser_errors':errors,'upstream':'local HTTP model fixture; WeChat mocked','checks':['login','actual HTTP SSE','generation','theme','titles','deai','image','clipboard','embedded HTML export','WeChat success response','history reload','mobile overflow','cancelled real stream refunds and preserves article']},ensure_ascii=False,indent=2),encoding='utf8')
 print('PASS browser pipeline, screenshots:',out)
 browser.close()
