(() => {
  if (window.__behaviorObserver || window.top !== window.self) return;
  window.__behaviorObserver = true;
  const pages = new Set(['home','workbench','wechat-plus','one-click-writing','qihaoshou','hotspots','lowfans','xiaohongshu','tie-tu','viral-remix','article-visual','xhs-extract','douyin-extract','bookshelf','market','pricing','pay','wallet']);
  let visitor;
  try { visitor = sessionStorage.getItem('behavior-visitor'); if (!/^[a-f0-9]{32}$/.test(visitor || '')) { const bytes = crypto.getRandomValues(new Uint8Array(16)); visitor = Array.from(bytes, n => n.toString(16).padStart(2,'0')).join(''); sessionStorage.setItem('behavior-visitor', visitor); } } catch { return; }
  const currentPage = () => { const name = location.pathname.replace(/^\/+|\/+$/g,'') || 'home'; return pages.has(name) ? name : null; };
  let page = currentPage(), last = Date.now(), interaction = 0;
  function send(event, seconds = 0, which = page) {
    if (!which) return;
    const data = JSON.stringify({visitor, page:which, event, seconds, device:matchMedia('(max-width: 767px)').matches?'mobile':'desktop'});
    fetch('/api/behavior', {method:'POST',headers:{'Content-Type':'application/json'},body:data,credentials:'same-origin',keepalive:true}).catch(()=>{});
  }
  function flush() {
    const now = Date.now();
    if (document.visibilityState === 'visible' && now - interaction < 60000) {
      const seconds = Math.min(30, Math.floor((now-last)/1000));
      if (seconds > 0) send('active_time',seconds);
    }
    last = now;
  }
  function navigate() { const next=currentPage(); if(next!==page) { flush(); page=next; if(page)send('page_view'); } }
  for (const key of ['pushState','replaceState']) { const original=history[key]; history[key]=function(...args){ const out=original.apply(this,args); navigate(); return out; }; }
  addEventListener('popstate',navigate);
  addEventListener('pagehide',flush);
  document.addEventListener('visibilitychange',()=>{ if(document.visibilityState==='hidden') flushHidden(); else last=Date.now(); });
  function flushHidden() { const now=Date.now(); if(now-interaction<60000){const seconds=Math.min(30,Math.floor((now-last)/1000)); if(seconds>0)send('active_time',seconds);} last=now; }
  ['pointerdown','keydown','scroll','touchstart'].forEach(type=>document.addEventListener(type,e=>{if(e.isTrusted)interaction=Date.now();},{passive:true}));
  document.addEventListener('click', e=>{
    const el=e.target.closest('a,button'); if(!el || !e.isTrusted || el.disabled)return;
    const href=el.getAttribute('href') || '';
    let event;
    const selectors={'#viral-remix-start':'remix_analyze','.viral-generate':'remix_generate','#remix-save-action':'remix_save','#av-analyze':'article_analyze','#av-download-all':'article_download','#xhs-extract-start':'xhs_extract','#douyin-extract-start':'douyin_extract','[data-wp-send]':'plus_send','[data-wp-copy]':'plus_copy'};
    event=Object.entries(selectors).find(([selector])=>el.matches(selector))?.[1];
    if(page==='pay' && el.id==='submit')event='checkout_submit';
    if(href==='/pricing') event='open_pricing';
    const target=href.match(/^\/pay\?package=(starter|pro|master)$/); if(target)event='choose_'+target[1];
    if(event)send(event);
  },true);
  if(page)send('page_view');
  setInterval(flush,15000);
})();
