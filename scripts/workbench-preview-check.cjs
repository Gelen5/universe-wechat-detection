const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const path = require('node:path');
(async()=>{
 const directory=path.resolve(process.argv[2]);
 const browser=await chromium.launch();
 try {
  const page=await browser.newPage({viewport:{width:390,height:844}});
  const errors=[]; page.on('pageerror',e=>errors.push(e.message));
  await page.goto('file:///'+path.join(directory,'preview.html').replaceAll('\\','/'));
  await page.waitForFunction(()=>[...document.images].every(i=>i.complete));
  const report=await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,
   images:[...document.images].map(i=>({loaded:i.naturalWidth>0,width:i.naturalWidth,height:i.naturalHeight,embedded:i.src.startsWith('data:image/')})),
   headings:[...document.querySelectorAll('h1,h2')].map(h=>({text:h.textContent,width:h.getBoundingClientRect().width,height:h.getBoundingClientRect().height})),
   text:document.querySelector('#article-content').innerText}));
  report.errors=errors;
  await page.evaluate(()=>{
    Object.defineProperty(navigator,'clipboard',{value:{write:async items=>{
      const item=items[0];
      globalThis.copiedPreview={html:await (await item.getType('text/html')).text(),text:await (await item.getType('text/plain')).text()};
    }},configurable:true});
  });
  await page.locator('#copy-article').click();
  await page.waitForFunction(()=>!!globalThis.copiedPreview);
  report.clipboard=await page.evaluate(()=>({images:new DOMParser().parseFromString(copiedPreview.html,'text/html').querySelectorAll('img[src^="data:image/"]').length,styled:copiedPreview.html.includes('style='),plainIsText:!copiedPreview.text.includes('<section')}));
  if(report.clipboard.images!==2||!report.clipboard.styled||!report.clipboard.plainIsText) throw Error('Clipboard content failed');
  if(report.scrollWidth>report.width || report.images.length!==2 || report.images.some(i=>!i.loaded||!i.embedded) || errors.length) throw Error(JSON.stringify(report));
  await page.screenshot({path:path.join(directory,'mobile-preview.png'),fullPage:true});
  await page.setViewportSize({width:1440,height:900});
  await page.screenshot({path:path.join(directory,'desktop-preview.png'),fullPage:true});
  fs.writeFileSync(path.join(directory,'browser-check.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({...report,text:report.text.length+' characters'}));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
