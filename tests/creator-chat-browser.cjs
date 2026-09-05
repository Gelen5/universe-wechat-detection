const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const root = path.resolve(__dirname, '..');
    await page.route('http://workbench.test/**', async route => {
      const url = new URL(route.request().url());
      if (url.pathname.startsWith('/api/')) {
        return route.fulfill({status: 401, contentType: 'application/json', body: '{}'});
      }
      const file = path.join(root, url.pathname === '/' ? 'static/index.html' : url.pathname);
      if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return route.fulfill({status: 404, body: ''});
      const ext = path.extname(file);
      return route.fulfill({body: fs.readFileSync(file), contentType: ({'.html':'text/html', '.js':'application/javascript', '.css':'text/css'})[ext] || 'application/octet-stream'});
    });
    let calls = 0;
    let result;
    await page.route('**/api/tasks', async route => {
      const request = route.request().postDataJSON().payload;
      calls++;
      if (calls === 2) assert.equal(request.session_id, 'browser-session');
      result = {session: {
        id: 'browser-session', conversation: [{role:'user',content:request.message}, {role:'assistant',content:'完成'}],
        artifacts: {draft: {session_id:'draft-id', body:'文案保留', cards:[], titles:[], precheck:{status:'revise'}}},
      }};
      if (request.skill === 'morning') result.session.artifacts = {draft: {title:'早安', copies:['早安祝福文案'], mode:'sticker', cards:[{index:1}], images:[{index:1,url:'/api/creator-tools/assets/tie-tu/test/card-01.png'}]}};
      if (request.skill === 'diagnose') result.session.artifacts = {report:{header:{},scores:{},works:[],web_insights:{}}};
      if (request.skill === 'hit-detector') result.session.artifacts = {report:{scores:{},suggestions:[]}};
      if (request.skill === 'tie-tu') result.session.artifacts = {draft:{title:'纯文案',copy:'测试文案',cards:[]}};
      await route.fulfill({contentType: 'application/json', body: JSON.stringify({job: {id: 'test-job', session_id: 'browser-session'}})});
    });
    await page.route('**/api/tasks/test-job', route => route.fulfill({contentType:'application/json', body:JSON.stringify({job:{status:'succeeded',result}})}));
    await page.route('**/api/creator-tools/assets/**', route => route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a/6kAAAAASUVORK5CYII=', 'base64')}));
    await page.goto('http://workbench.test/#xiaohongshu');
    await page.evaluate(() => {
      document.querySelector('#auth-modal').hidden = true;
      document.querySelector('#xiaohongshu').hidden = false;
    });
    const form = page.locator('#xiaohongshu .creator-conversation');
    await form.locator('textarea').fill('只要文案，不要图片');
    await form.locator('[type=submit]').click();
    await page.waitForFunction(() => document.querySelector('#xhs-body')?.value === '文案保留');
    assert(await page.locator('#xhs-images').isHidden());
    await page.locator('#xhs-body').fill('手动编辑保留');
    await form.locator('textarea').fill('解释一下');
    await form.locator('[type=submit]').click();
    await page.waitForFunction(() => !document.querySelector('.creator-conversation button').disabled);
    assert.equal(await page.locator('#xhs-body').inputValue(), '手动编辑保留');
    assert.equal(calls, 2);
    for (const id of ['tie-tu', 'hit-detector', 'diagnose', 'morning-generator']) {
      assert.equal(await page.locator(`#${id} .creator-conversation`).count(), 1);
      await page.evaluate(id => setActiveView(id === 'morning-generator' ? 'morning' : id), id);
      const conversation = page.locator(`#${id} .creator-conversation`);
      await conversation.locator('textarea').fill('测试');
      await conversation.locator('[type=submit]').click();
      await page.waitForFunction(id => !document.querySelector(`#${id} .creator-conversation [type=submit]`).disabled, id);
      assert.equal(await conversation.locator('[role=status]').textContent(), '已完成');
    }
    await page.waitForFunction(() => document.querySelector('#morning-generator .creator-chat-output img')?.naturalWidth > 0);
    assert.equal(await page.locator('#morning-generator .creator-chat-output').getByText('下载 HTML', {exact:true}).count(), 0);
    for (const width of [1440, 390]) {
      await page.setViewportSize({width, height:900});
      await page.screenshot({path:path.join(require('os').tmpdir(), `creator-chat-${width}.png`),fullPage:true});
    }
    console.log('PASS: queue, session reuse, no-image rendering, answer preserves editor, five entrypoints');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
