/* Desktop material only: keep every existing composer, route and event handler. */
(() => {
  const workspace = document.getElementById('workbench');
  if (!workspace) return;
  const desktop = matchMedia('(min-width: 1101px)');
  const wrap = document.getElementById('nav-menu-wrap');
  const avatar = document.getElementById('nav-avatar');
  const menu = document.getElementById('settings-menu');
  let settingsToggle;
  if (wrap && avatar && menu) {
    settingsToggle = document.createElement('button');
    settingsToggle.id = 'mint-settings-toggle'; settingsToggle.type = 'button';
    settingsToggle.title = '设置'; settingsToggle.setAttribute('aria-label', '打开设置菜单');
    settingsToggle.setAttribute('aria-haspopup', 'menu'); settingsToggle.setAttribute('aria-controls', menu.id);
    settingsToggle.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9.5 3-.7 2.3-2 .9-2.2-.6-2.5 4.2 1.6 1.7v2.3L2.1 15l2.5 4.3 2.2-.6 2 .9.7 2.4h5l.7-2.4 2-.9 2.2.6 2.5-4.3-1.6-1.2v-2.3l1.6-1.7-2.5-4.2-2.2.6-2-.9L14.5 3z"/><circle cx="12" cy="12.5" r="3"/></svg>';
    wrap.insertBefore(settingsToggle, menu);
    // Reuse the original trigger so the existing menu and actions stay intact.
    settingsToggle.addEventListener('click', () => avatar.click());
    const syncMenu = () => settingsToggle.setAttribute('aria-expanded', String(!menu.hidden));
    new MutationObserver(syncMenu).observe(menu, {attributes:true, attributeFilter:['hidden']});
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && document.body.classList.contains('mint-wechat') && !menu.hidden) {
        avatar.click(); settingsToggle.focus();
      }
    });
    syncMenu();
  }
  const sync = () => {
    const active = desktop.matches && !workspace.hidden;
    document.body.classList.toggle('mint-wechat', active);
    if (settingsToggle) settingsToggle.hidden = !active;
  };
  new MutationObserver(sync).observe(workspace, {attributes:true, attributeFilter:['hidden']});
  desktop.addEventListener('change', sync);
  const stages = document.getElementById('workbench-stage-nav');
  if (stages) {
    const syncStages = () => stages.querySelectorAll('button').forEach(button => {
      button.dataset.mintComplete = String(button.querySelector('small')?.textContent.trim() === '已完成');
    });
    new MutationObserver(syncStages).observe(stages, {childList:true, subtree:true, characterData:true});
    syncStages();
  }
  sync();
})();
