/* Presentation only: reuse all existing navigation and Skill request handlers. */
(() => {
  const header = document.querySelector('.v3-topbar');
  const nav = header.querySelector('.app-tabs');
  // Keep this entry explicit: the sidebar is reconstructed below and older
  // cached/embedded shells may not contain the server-rendered link yet.
  function ensureViralRemixEntry() {
    let entry = nav.querySelector('[data-view="viral-remix"]');
    if (!entry) {
      entry = document.createElement('a');
      entry.href = '/viral-remix'; entry.dataset.view = 'viral-remix';
      entry.innerHTML = '<svg class="tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="m8 15 3-3 2 2 3-4 2 3"/><circle cx="8.5" cy="8.5" r="1.2"/><path d="M16 3v4M14 5h4"/></svg><span>爆款贴图复刻</span>';
    }
    const tieTu = nav.querySelector('[data-view="tie-tu"]');
    if (tieTu) tieTu.insertAdjacentElement('afterend', entry);
  }
  ensureViralRemixEntry();
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
  // 菜单清单只有一个来源：/static/routes.js。这里不再写死分组与顺序。
  const NAV = window.APP_NAV;
  if (NAV) {
    function buildNavItem(href, spec) {
      const a = document.createElement('a');
      a.href = href;
      // 独立页面不能挂 data-view：app.js 会把它当应用内视图处理，导致白屏。
      if (spec.view && !spec.page) a.dataset.view = spec.view;
      a.innerHTML = `${spec.icon}<span>${spec.label}</span>`;
      return a;
    }
    const extras = {};
    for (const spec of NAV.extras) extras[spec.href] = spec;
    const home = nav.querySelector('a[href="/"]');
    const frag = document.createDocumentFragment();
    for (const [label, hrefs] of NAV.notionPlan) {
      const cap = document.createElement('div');
      cap.className = 'nav-group-label';
      cap.textContent = label;
      frag.appendChild(cap);
      for (const href of hrefs) {
        let el = nav.querySelector(`a[href="${href}"], a[data-view][href$="${href}"]`);
        if (!el && extras[href]) el = buildNavItem(href, extras[href]);
        if (el) frag.appendChild(el);
      }
    }
    nav.innerHTML = '';
    if (home) nav.appendChild(home);
    nav.appendChild(frag);
  }

  // Nav anchors are optional now: a hidden module (e.g. /diagnose) has none,
  // and a bare querySelector would throw here and abort the whole script.
  const relabel = (view, label) => {
    const span = nav.querySelector(`[data-view=${view}] span`);
    if (span) span.textContent = label;
  };
  relabel('diagnose', '账号诊断');
  relabel('hit-detector', '发布前复核');
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
