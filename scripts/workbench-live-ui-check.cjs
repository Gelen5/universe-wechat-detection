const { chromium }=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch();
 try{
  const context=await browser.newContext({storageState:process.env.QA_STORAGE_STATE,viewport:{width:1440,height:900}});
  const page=await context.newPage();
  await page.goto('http://127.0.0.1:8765/workbench');
  assert.equal((await context.request.get('http://127.0.0.1:8765/health')).status(),200);
  const actual=JSON.parse(fs.readFileSync('output/workbench/qa-chain-20260905-v2/session.json','utf8'));
  // Presentation test using real generated plan; does not create an account session.
  await page.evaluate(s=>renderWorkbenchSession({...s,current_step:5,images:[],image_plan:{...s.image_plan,status:'awaiting_confirmation'}}),actual);
  assert.match(await page.locator('#run-next').innerText(),/确认方案/);
  assert.equal(await page.locator('#generated-images').isVisible(),true);
  assert.match(await page.locator('#generated-images').innerText(),/配图方案/);
  let sent;
  await page.route('**/api/workbench/chat',async route=>{sent=route.request().postDataJSON();await route.fulfill({json:{session:{...actual,current_step:5}}});});
  if(!await page.locator('#workbench-topic').isVisible()) await page.locator('#assistant-toggle').click();
  await page.locator('#workbench-topic').fill('正文图换成清单示意');
  await page.locator('#start-workbench').click();
  await page.waitForTimeout(200);
  assert.equal(sent.action,'revise_image_plan');
  const anon=await browser.newContext();
  assert.equal((await anon.request.get('http://127.0.0.1:8765/api/workbench/sessions/not-owned')).status(),401);
  console.log('PASS live service, image-plan confirmation, plan revision routing, auth');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
