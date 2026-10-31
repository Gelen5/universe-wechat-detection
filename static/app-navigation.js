/* Install navigation before the large application bundle and its handlers load. */
(() => {
  const views = new Map([
    ['/', 'home'], ['/workbench', 'workbench'], ['/one-click-writing', 'one-click-writing'],
    ['/xiaohongshu', 'xiaohongshu'], ['/tie-tu', 'tie-tu'], ['/viral-remix', 'viral-remix'], ['/diagnose', 'diagnose'],
    ['/hit-detector', 'hit-detector'], ['/morning-generator', 'morning'],
    ['/market', 'market'], ['/hotspots', 'hotspots'],
  ]);
  const normalize = path => path.replace(/\/+$/, '') || '/';
  const initial = views.get(normalize(location.pathname));
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
