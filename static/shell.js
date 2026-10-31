/* Shared navigation behavior for the app and standalone resource pages. */
(() => {
  // Standalone resource pages use the same sign-in requirement as the main shell.
  if (!document.getElementById('auth-modal') && !new URLSearchParams(location.search).has('embed')) {
    fetch('/api/auth/me',{credentials:'same-origin',cache:'no-store'}).then(r=>{
      if(r.status===401)location.replace('/?register=1');
    }).catch(()=>{});
  }
  const nav = document.querySelector('.v3-topbar .app-tabs');
  if (!nav) return;
  // 清单来自 /static/routes.js：不再在本文件维护第二份路由表。
  const NAV = window.APP_NAV;
  if (!NAV) return;
  const routes = NAV.shellRoutes;
  const menu = document.createElement('dialog');
  menu.className = 'shell-menu'; menu.id = 'shell-more-menu';
  menu.setAttribute('aria-labelledby', 'shell-more-title');
  const heading = document.createElement('h2'); heading.id = 'shell-more-title'; heading.textContent = '全部功能';
  const close = document.createElement('button'); close.type = 'button'; close.textContent = '关闭';
  const list = document.createElement('nav'); list.setAttribute('aria-label', '全部功能');
  menu.append(heading, close, list); document.body.append(menu);
  const ordered = document.createDocumentFragment();
  let lastGroup = null;
  for (const [href, label, short] of routes) {
    let link = nav.querySelector(`a[href="${href}"]`);
    const spec = NAV.itemFor(href);
    if (!link && spec && spec.fallback) {
      link = document.createElement('a'); link.href = href;
      // 独立页面不能挂 data-view：app.js 会把它当应用内视图处理，导致白屏。
      if (spec.view && !spec.page) link.dataset.view = spec.view;
      link.innerHTML = `${spec.icon}<span>${spec.label}</span>`;
    }
    if (!link) continue;
    if (spec && spec.group && spec.group !== lastGroup) {
      const caption = document.createElement('div'); caption.className = 'nav-group-label';
      caption.textContent = spec.group; ordered.append(caption);
      lastGroup = spec.group;
    }
    ordered.append(link);
    link.setAttribute('aria-label', label); link.title = label;
    const text = link.querySelector('span'); if (text) text.textContent = label;
    if (short) {
      link.dataset.shellPrimary = 'true';
      const compact = document.createElement('span'); compact.className = 'nav-short';
      compact.textContent = short; compact.setAttribute('aria-hidden', 'true'); link.append(compact);
    }
    const choice = document.createElement('a'); choice.href = href; choice.textContent = label;
    choice.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
      event.preventDefault(); menu.close(); link.click();
    });
    list.append(choice);
  }
  const more = document.createElement('button'); more.type = 'button'; more.className = 'shell-mobile-more';
  more.textContent = '更多'; more.setAttribute('aria-controls', menu.id); more.setAttribute('aria-expanded', 'false');
  more.addEventListener('click', () => { menu.showModal(); more.setAttribute('aria-expanded', 'true'); });
  close.addEventListener('click', () => menu.close());
  menu.addEventListener('close', () => more.setAttribute('aria-expanded', 'false'));
  menu.addEventListener('click', event => {
    const rect = menu.getBoundingClientRect();
    if (event.target === menu && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) menu.close();
  });
  nav.replaceChildren(ordered, more);
  const sync = () => {
    for (const link of nav.querySelectorAll('a')) {
      if(link.classList.contains('active'))link.setAttribute('aria-current','page');
      else link.removeAttribute('aria-current');
    }
    const secondaryActive = !!nav.querySelector('a.active:not([data-shell-primary])');
    if (more.classList.contains('active') !== secondaryActive) more.classList.toggle('active', secondaryActive);
    for (const choice of list.children) {
      const source = nav.querySelector(`a[href="${choice.getAttribute('href')}"]`);
      if (source?.classList.contains('active')) choice.setAttribute('aria-current', 'page');
      else choice.removeAttribute('aria-current');
    }
  };
  new MutationObserver(sync).observe(nav, {subtree:true, attributes:true, attributeFilter:['class']}); sync();
  matchMedia('(max-width: 760px)').addEventListener('change', event => { if (!event.matches && menu.open) menu.close(); });
})();
