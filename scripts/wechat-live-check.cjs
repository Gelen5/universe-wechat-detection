const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async()=>{
 const b=await chromium.launch();
 try {
 const p=await b.newPage({storageState:process.env.QA_STORAGE_STATE,viewport:{width:1440,height:1000}});
 const dialogs=[];
 p.on('dialog',async d=>{dialogs.push(d.message());console.log('DIALOG',d.message());await d.dismiss();});
 p.on('pageerror',e=>console.log('PAGE_ERROR',e.message));
 await p.goto('http://127.0.0.1:8765/workbench');
 const prompt='写一篇公众号文章：下班后，怎样用30分钟整理写作素材。\n目标读者：有全职工作、刚开始写公众号的人。\n篇幅：800—1000字。语气自然、具体，不说教。\n结构：从一个常见困境开始，给出三个可操作步骤，以一个小行动结尾。\n事实边界：不编造我的亲身经历、人物故事、数据或研究引用。';
 await p.locator('#workbench-topic').fill(prompt);
 await p.locator('#workbench-topic').evaluate(e=>{e.style.height='190px';e.style.maxHeight='240px'});
 await p.screenshot({path:'D:/Download/wechat-live-input.png'});
 const accepted=p.waitForResponse(r=>r.url().endsWith('/api/workbench/sessions'));
 await p.locator('#start-workbench').click();
 const r=await accepted; const data=await r.json();
 console.log('CREATE',r.status(),JSON.stringify(data));
 if(!r.ok()) {await p.screenshot({path:'D:/Download/wechat-live-failure.png'});return;}
 for(let i=0;i<180;i++) {
   await p.waitForTimeout(1500);
   if(dialogs.length) { console.log('INPUT_PRESERVED',await p.locator('#workbench-topic').inputValue()===prompt);await p.screenshot({path:'D:/Download/wechat-live-failure.png'});return; }
   if(await p.locator('.adopt-topic').count())break;
   if(i%20===0) console.log('WAIT',await p.locator('#workbench-status').innerText());
 }
 if(!await p.locator('.adopt-topic').count()) throw Error('选题等待超时，未继续生成');
 await p.screenshot({path:'D:/Download/wechat-live-topics.png'});
 for(const target of [2,3,4,5,6,7]) {
   if(target===2)await p.locator('.adopt-topic').first().click(); else await p.locator('#run-next').click();
   await p.waitForFunction(n=>typeof workbenchSession!=='undefined'&&workbenchSession?.current_step===n,target,{timeout:300000});
   console.log('STEP',target,'OK');
   await p.screenshot({path:'D:/Download/wechat-live-step-'+target+'.png'});
 }
 console.log('SESSION',await p.evaluate(()=>JSON.stringify({id:workbenchSession.id,preview_url:workbenchSession.preview_url,review:workbenchSession.review})));
 } finally {await b.close()}
})().catch(e=>{console.error(e.message);process.exitCode=1});
