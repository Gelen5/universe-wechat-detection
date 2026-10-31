/* Install navigation before the large application bundle and its handlers load. */
(() => {
  // 路由 → 视图的映射来自 /static/routes.js，避免这里再维护一份清单。
  const NAV = window.APP_NAV;
  if (!NAV) return;
  const normalize = path => (path || '/').replace(/\/+$/, '') || '/';
  const views = { get: path => NAV.viewFor(normalize(path)) };
  const initial = views.get(location.pathname);
  if (initial) document.documentElement.dataset.initialView = initial;
  let pending = null;
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link || event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
        || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
    const url = new URL(link.href, location.href);
    const view = url.origin === location.origin && !url.search && !url.hash
      ? views.get(normalize(url.pathname)) : null;
    if (!view) return;
    event.preventDefault();
    // During startup, retain the last click instead of navigating the document.
    if (!window.AppNav) {
      pending = view;
      document.documentElement.dataset.initialView = view;
      return;
    }
    // Links handled by the existing application handlers keep those behaviors.
    if (!link.hasAttribute('data-view')) window.AppNav.setActiveView(view, true);
  }, true);
  window.addEventListener('app-nav-ready', () => {
    if (pending) window.AppNav.setActiveView(pending, true);
    pending = null;
    delete document.documentElement.dataset.initialView;
  }, {once: true});
})();
