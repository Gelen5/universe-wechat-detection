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
  function buildSidebar() {
    if (!NAV) return;
    // 手机端沿用 shell.js 的扁平底栏，不做分组（分组只服务桌面侧栏）。
    if (window.matchMedia('(max-width: 760px)').matches) return;
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
    const moreBtn = nav.querySelector('.shell-mobile-more');
    const groups = document.createElement('div');
    groups.className = 'nav-groups';
    for (const [label, hrefs] of NAV.notionPlan) {
      const section = document.createElement('section');
      section.className = 'nav-group';
      section.dataset.group = label;
      const cap = document.createElement('div');
      cap.className = 'nav-group-label';
      cap.textContent = label;
      section.appendChild(cap);
      for (const href of hrefs) {
        let el = nav.querySelector(`a[href="${href}"], a[data-view][href$="${href}"]`);
        if (!el && extras[href]) el = buildNavItem(href, extras[href]);
        if (el) section.appendChild(el);
      }
      // 一个可见条目都没有的组整组不渲染，避免只剩一个空标题。
      if (section.children.length <= 1) continue;
      groups.appendChild(section);
    }
    nav.innerHTML = '';
    if (home) nav.appendChild(home);
    nav.appendChild(groups);
    if (moreBtn) nav.appendChild(moreBtn);
    // 用户要求取消折叠：工具 / 资源 / 账户 直接展开，不再生成「更多功能」开关。
    // 需要重新收起时，把下面这段放回去，并在 ui-system.css 里恢复默认 display:none。
    // if (groups.querySelector('[data-group="工具"]')) { ... }
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
  const names = {'/diagnose':'账号诊断','/hit-detector':'发布前复核'};
  document.querySelectorAll('#home .hc-card').forEach(a=>{ if(names[a.getAttribute('href')]) a.querySelector('.t').textContent=names[a.getAttribute('href')]; });

  // shell.js 是 defer 脚本，会在本文件之后重建一次导航，所以分组要等它跑完再收一次。
  function scheduleSidebarBuild() {
    buildSidebar();
    window.setTimeout(buildSidebar, 0);
  }
  if (document.readyState === 'complete') scheduleSidebarBuild();
  else window.addEventListener('load', scheduleSidebarBuild, {once: true});
})();
