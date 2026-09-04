// Run with PLAYWRIGHT_MODULE and QA_STORAGE_STATE pointing to local test dependencies.
// No model calls: request failures and generated content are explicit UI fixtures.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ storageState:process.env.QA_STORAGE_STATE, viewport:{width:1440,height:900} });
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    page.on('dialog',d=>d.dismiss());
    const base=process.env.QA_BASE_URL || 'http://127.0.0.1:8765';
    for (const width of [1440,1024,390]) {
      await page.setViewportSize({width,height:900});
      for (const route of ['', 'workbench','xiaohongshu','tie-tu','hit-detector','diagnose','morning-generator']) {
        await page.goto(base+'/'+route);
        await page.waitForSelector('#assistant-toggle',{state:'attached'});
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${width} ${route} overflow`);
        if(width>760) assert.ok(await page.locator('.app-shell').evaluate(e=>e.getBoundingClientRect().x)>=190);
        else {
          await page.locator('.workspace-menu-toggle').click();
          assert.equal(await page.locator('.app-tabs').isVisible(),true);
          await page.keyboard.press('Escape');
          assert.equal(await page.locator('.app-tabs').isVisible(),false);
        }
        console.log('PASS layout',width,route||'home');
      }
    }
    await page.setViewportSize({width:1440,height:900});
    await page.goto(base+'/workbench');
    const input=page.locator('#workbench-topic');
    await input.fill('布局测试，不能丢失的写作需求');
    await page.locator('#assistant-toggle').click();
    assert.equal(await page.locator('#creation-assistant').isVisible(),false);
    await page.locator('.begin-writing').click();
    assert.equal(await input.inputValue(),'布局测试，不能丢失的写作需求');
    assert.equal(await input.evaluate(e=>e===document.activeElement),true);
    await page.evaluate(()=>renderWorkbenchSession({id:'ui-fixture',current_step:4,topic:'测试文章：让正文成为创作的中心',article:'这是用于验证界面布局的测试正文，不是模型生成结果。\n\n写作时，正文应该有足够的阅读空间，工具和对话可以按需展开。',review:{source:'universe-delete-ai-skill',action:'测试审计数据',audit:{status:'success',original_signal_total:12,revision_signal_total:0,complete_sentence_ratio:1,missing_protected_spans:{},warnings:[]}},conversation:[],versions:[],framework:{name:'测试框架',outline:['引入','展开','结尾']}}));
    assert.equal(await page.locator('#article-editor').isVisible(),true);
    assert.ok((await page.locator('#score-report').innerText()).includes('改写后信号数'));
    assert.equal(await page.locator('#score-report .score-ring').count(),0);
    await page.locator('#studio-details-toggle').click();
    assert.equal(await page.locator('#studio-details').isVisible(),true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#studio-details').isVisible(),false);
    if(process.env.QA_SCREENSHOT_DIR) await page.screenshot({path:process.env.QA_SCREENSHOT_DIR+'/notion-article.png'});
    await page.setViewportSize({width:390,height:844});
    if(process.env.QA_SCREENSHOT_DIR) await page.screenshot({path:process.env.QA_SCREENSHOT_DIR+'/notion-mobile.png'});
    await page.setViewportSize({width:1440,height:900});
    await page.route('**/api/tasks',r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'UI test: unavailable'})}));
    for(const [route,fields] of [['xiaohongshu',['#xhs-topic']],['tie-tu',['#tie-topic']],['hit-detector',['#hit-title','#hit-body']]]) {
      await page.goto(base+'/'+route);
      for(const f of fields) await page.locator(f).fill('UI 测试素材，失败后应保留。');
      const button=page.locator('.studio-tool:not([hidden]) form button[type=submit]');
      const response=page.waitForResponse(r=>r.url().endsWith('/api/tasks'));
      await button.click(); await response;
      await page.waitForFunction(()=>!document.querySelector('.studio-tool:not([hidden]) form button[type=submit]').disabled);
      for(const f of fields) assert.equal(await page.locator(f).inputValue(),'UI 测试素材，失败后应保留。');
      console.log('PASS failure recovery',route);
    }
    assert.deepEqual(errors,[]);
    console.log('PASS assistant, inspector, audit, navigation, no page errors');
  } finally { await browser.close(); }
})().catch(e=>{ console.error(e); process.exitCode=1; });
