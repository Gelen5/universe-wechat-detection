const { chromium } = require('playwright');
const assert = require('assert');
const fs = require('fs');
const path = require('path');

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const root = path.resolve(__dirname, '..');
    let createPayload;
    let jobPolls = 0;

    await page.route('http://workbench.test/**', async route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/api/workbench/sessions' && route.request().method() === 'POST') {
        createPayload = route.request().postDataJSON();
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ job: { id: 'job-1' } }) });
      }
      if (url.pathname === '/api/workbench/jobs/job-1') {
        jobPolls += 1;
        if (jobPolls === 1) return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ job: { status: 'running' } }) });
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ job: { status: 'completed' }, session: {
          id: 'session-1', mode: createPayload.mode, current_step: 1, status: 'awaiting_topic', topic: createPayload.topic,
          conversation: [{ role: 'user', content: createPayload.topic }, { role: 'assistant', content: '我查询了近期信号，整理出 10 个方向。' }],
          suggestions: Array.from({ length: 10 }, (_, i) => ({ id: i + 1, title: `选题 ${i + 1}`, reason: '近期信号与读者问题相交', type: '热点回应', competition: '中', heat: 8, fan_score: 82 })),
          skill_execution: [{ step: 1, name: '选题', status: 'passed', operation: 'topic-selection' }], versions: []
        } }) });
      }
      if (url.pathname === '/api/workbench/steps') {
        const body = route.request().postDataJSON();
        assert.equal(body.step, 2);
        assert.equal(body.selection, 1);
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ status: 'success', session: {
          id: 'session-1', current_step: 2, status: 'ready_for_review', topic: '选题 1',
          conversation: [{ role: 'user', content: createPayload.topic }, { role: 'assistant', content: '已采用选题 1，并生成文章框架。' }],
          suggestions: [], framework: { name: 'SCQA', outline: ['具体场景', '矛盾展开', '行动建议'] },
          skill_execution: [{ step: 1, name: '选题', status: 'passed' }, { step: 2, name: '框架', status: 'passed' }], versions: []
        } }) });
      }
      if (url.pathname.startsWith('/api/')) return route.fulfill({ status: 401, contentType: 'application/json', body: '{}' });
      const relative = url.pathname.startsWith('/static/') ? url.pathname.slice(1) : 'static/index.html';
      const file = path.join(root, relative);
      if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
      const type = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' }[path.extname(file)] || 'application/octet-stream';
      return route.fulfill({ body: fs.readFileSync(file), contentType: type });
    });

    await page.goto('http://workbench.test/workbench');
    await page.evaluate(() => { document.querySelector('#auth-modal').hidden = true; setActiveView('workbench'); });
    assert.equal(await page.locator('#workflow-steps').isVisible(), false);
    assert.equal(await page.locator('#studio-details').isVisible(), false);
    assert.equal(await page.locator('.conversation-workbench-layout > .conversation-panel').count(), 1);
    assert.equal(await page.locator('#creation-assistant > #workbench-result').count(), 1);
    assert.equal(await page.locator('#workbench-mode-picker .mode-option').count(), 3);
    assert.equal(await page.locator('#workbench-mode-picker').isVisible(), true);

    await page.locator('[data-starter-prompt]').first().click();
    assert((await page.locator('#workbench-topic').inputValue()).includes('最近一周'));
    await page.locator('#start-workbench').click();
    await page.waitForFunction(() => document.querySelector('#workbench')?.classList.contains('is-running'));
    assert.equal(await page.locator('.composer-shell').isVisible(), false);
    assert.equal(await page.locator('.flow-actionbar').isVisible(), false);
    assert.equal(await page.locator('#workbench-progress').isVisible(), true);
    await page.waitForFunction(() => document.querySelectorAll('.adopt-topic').length === 10);
    assert(createPayload.topic.includes('最近一周'));
    assert.equal(createPayload.mode, 'interactive');
    assert.equal(await page.locator('.chat-message.from-user').count(), 1);
    assert.equal(await page.locator('.adopt-topic').count(), 10);
    assert.equal(await page.locator('#workbench-mode-picker').isVisible(), false);
    assert.equal(await page.locator('.composer-shell').isVisible(), true);
    assert((await page.locator('#workbench-execution-evidence summary').innerText()).includes('查看本次 Skill 执行记录'));
    assert(!(await page.locator('#workbench-execution-evidence summary').innerText()).includes('/8'));

    await page.locator('.adopt-topic').first().click();
    await page.waitForFunction(() => document.querySelector('.studio-framework')?.textContent.includes('SCQA'));
    assert.equal(await page.locator('.studio-framework').isVisible(), true);
    assert.equal(await page.locator('#creation-assistant .studio-framework').count(), 1);
    assert.equal(await page.locator('.studio-framework li').first().isVisible(), true);
    const firstFrameworkItem = await page.locator('.studio-framework li').first().boundingBox();
    const panelHeader = await page.locator('.conversation-panel-head').boundingBox();
    assert(firstFrameworkItem.y >= panelHeader.y + panelHeader.height);
    assert(firstFrameworkItem.y < 900);

    await page.screenshot({ path: path.join(root, 'qa-chatgpt', 'workbench-chat.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.locator('#creation-assistant').isVisible(), true);
    assert.equal(await page.locator('#workbench-result').isVisible(), true);
    await page.screenshot({ path: path.join(root, 'qa-chatgpt', 'workbench-chat-mobile.png'), fullPage: true });
    console.log('PASS: mode selection, exclusive running state, artifact-first scrolling, quiet Skill evidence, responsive chat flow');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
