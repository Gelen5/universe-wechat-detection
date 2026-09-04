/* Presentation only: reuse all existing navigation and Skill request handlers. */
(() => {
  const header = document.querySelector('.v3-topbar');
  const nav = header.querySelector('.app-tabs');
  nav.id = 'workspace-navigation';
  const menu = document.createElement('button');
  menu.type = 'button'; menu.className = 'workspace-menu-toggle';
  menu.textContent = '菜单'; menu.setAttribute('aria-controls', nav.id);
  menu.setAttribute('aria-expanded', 'false');
  header.prepend(menu);
  function closeMenu() { header.classList.remove('nav-open'); menu.setAttribute('aria-expanded','false'); }
  menu.addEventListener('click', () => {
    const open = header.classList.toggle('nav-open'); menu.setAttribute('aria-expanded', String(open));
  });
  const groups = [
    ['工作空间', ['home']],
    ['内容创作', ['workbench','xiaohongshu','tie-tu','morning']],
    ['分析与复核', ['diagnose','hit-detector']],
  ];
  for (const [label, ids] of groups) {
    const caption = document.createElement('div'); caption.className='nav-group-label'; caption.textContent=label;
    nav.append(caption);
    for (const id of ids) nav.append(nav.querySelector(`[data-view="${id}"]`));
  }
  nav.querySelector('[data-view=diagnose] span').textContent='账号诊断';
  nav.querySelector('[data-view=hit-detector] span').textContent='发布前复核';
  function syncNav() {
    // Some legacy theme selectors highlight href="/" on every route.
    nav.querySelectorAll('a').forEach(a => {
      const active = a.classList.contains('active');
      if(active) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current');
    });
  }
  new MutationObserver(syncNav).observe(nav,{subtree:true,attributes:true,attributeFilter:['class']});
  syncNav();
  nav.addEventListener('click', e => { if(e.target.closest('a')) closeMenu(); });
  document.addEventListener('keydown',e=>{ if(e.key==='Escape' && header.classList.contains('nav-open')) { closeMenu(); menu.focus(); } });
  document.addEventListener('click',e=>{ if(!header.contains(e.target)) closeMenu(); });
  const workspace = document.querySelector('#workbench');
  const toggle = document.querySelector('#assistant-toggle');
  function showAssistant(open) {
    workspace.classList.toggle('assistant-collapsed',!open);
    toggle.setAttribute('aria-expanded',String(open)); toggle.textContent=open?'收起助手':'打开助手';
  }
  toggle.addEventListener('click',()=>showAssistant(workspace.classList.contains('assistant-collapsed')));
  function focusComposer() {
    showAssistant(true);
    workspace.dataset.studioView='chat';
    workspace.querySelectorAll('.studio-switch button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.studioView==='chat')));
    document.querySelector('#workbench-topic').focus();
  }
  const decision = document.querySelector('#workbench-decision');
  const start = document.createElement('button'); start.type='button'; start.className='begin-writing'; start.textContent='输入我的写作需求 →';
  start.addEventListener('click',focusComposer);
  function syncEmpty() {
    if(workspace.dataset.stage==='0' && !decision.contains(start)) decision.append(start);
    else if(workspace.dataset.stage!=='0' && decision.contains(start)) start.remove();
  }
  new MutationObserver(syncEmpty).observe(decision,{childList:true});
  new MutationObserver(syncEmpty).observe(workspace,{attributes:true,attributeFilter:['data-stage']});
  syncEmpty();
  document.querySelector('#new-workbench-chat').addEventListener('click',()=>showAssistant(true));
  const names = {'/diagnose':'账号诊断','/hit-detector':'发布前复核'};
  document.querySelectorAll('#home .hc-card').forEach(a=>{ if(names[a.getAttribute('href')]) a.querySelector('.t').textContent=names[a.getAttribute('href')]; });
})();
