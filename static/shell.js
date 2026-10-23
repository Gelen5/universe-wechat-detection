/* Shared navigation behavior for the app and standalone resource pages. */
(() => {
  const nav = document.querySelector('.v3-topbar .app-tabs');
  if (!nav) return;
  const routes = [
    ['/', '首页', '首页'], ['/workbench', '公众号创作', '创作'],
    ['/one-click-writing', '公众号一键成文', '一键成文'],
    ['/xiaohongshu', '小红书'], ['/tie-tu', '贴图号'], ['/morning-generator', '早安祝福'],
    ['/diagnose', '账号诊断'], ['/hit-detector', '发布前复核'],
    ['/market', 'AI 超市', '超市'], ['/bookshelf', 'AI 书架'],
  ];
  const menu = document.createElement('dialog');
  menu.className = 'shell-menu'; menu.id = 'shell-more-menu';
  menu.setAttribute('aria-labelledby', 'shell-more-title');
  const heading = document.createElement('h2'); heading.id = 'shell-more-title'; heading.textContent = '全部功能';
  const close = document.createElement('button'); close.type = 'button'; close.textContent = '关闭';
  const list = document.createElement('nav'); list.setAttribute('aria-label', '全部功能');
  menu.append(heading, close, list); document.body.append(menu);
  const ordered = document.createDocumentFragment();
  const groups = {'/workbench': '内容创作', '/diagnose': '分析', '/market': '资源'};
  for (const [href, label, short] of routes) {
    const link = nav.querySelector(`a[href="${href}"]`);
    if (!link) continue;
    if (groups[href]) {
      const caption = document.createElement('div'); caption.className = 'nav-group-label';
      caption.textContent = groups[href]; ordered.append(caption);
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
