(() => {
  'use strict';

  const page = document.querySelector('#hotspots');
  if (!page) return;

  const list = page.querySelector('#hs-list');
  const chips = page.querySelector('#hs-platforms');
  const search = page.querySelector('#hs-search');
  const updated = page.querySelector('#hs-updated');
  const banner = page.querySelector('#hs-banner');

  const state = { platform: '', q: '', loaded: false };
  let timer = null;

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));

  function formatTime(value) {
    if (!value) return '尚未同步';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '尚未同步';
    return date.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  }

  async function api(path) {
    const response = await fetch(path, { credentials: 'same-origin' });
    if (!response.ok) throw new Error(`请求失败（${response.status}）`);
    return response.json();
  }

  function renderChips(platforms) {
    const total = platforms.reduce((sum, item) => sum + (item.count || 0), 0);
    const rows = [{ id: '', name: '全部', count: total, ok: true }, ...platforms];
    chips.innerHTML = rows.map((item) => `
      <button type="button" class="hs-chip${item.ok === false ? ' is-off' : ''}"
              data-platform="${escapeHtml(item.id)}"
              aria-pressed="${item.id === state.platform}">
        ${escapeHtml(item.name)}${item.count ? ` ${item.count}` : ''}
      </button>`).join('');
  }

  function renderList(items) {
    if (!items.length) {
      list.innerHTML = `<div class="hs-empty"><strong>这个筛选下没有热点</strong>换个平台，或清空搜索词。</div>`;
      return;
    }
    list.innerHTML = items.map((item, index) => `
      <article class="hs-row">
        <span class="hs-rank">${String(index + 1).padStart(2, '0')}</span>
        <div class="hs-main">
          <div class="hs-title"><a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a></div>
          <div class="hs-sub">
            <span>${escapeHtml(item.platform_zh || item.platform)}</span>
            ${item.hot ? `<b>${escapeHtml(item.hot)}</b>` : `<b>热搜 #${item.rank || 0}</b>`}
          </div>
        </div>
        <button type="button" class="hs-go" data-create="${escapeHtml(item.title)}" data-url="${escapeHtml(item.url)}">去创作</button>
      </article>`).join('');
  }

  function skeleton() {
    list.innerHTML = Array.from({ length: 6 }, () => '<div class="hs-skeleton"></div>').join('');
  }

  async function load() {
    skeleton();
    const params = new URLSearchParams({ limit: '80' });
    if (state.platform) params.set('platform', state.platform);
    if (state.q) params.set('q', state.q);
    try {
      const data = await api(`/api/hotspots?${params.toString()}`);
      renderChips(data.platforms || []);
      renderList(data.items || []);
      const when = formatTime(data.updated_at);
      updated.querySelector('span').textContent = when === '尚未同步' ? when : `更新于 ${when}`;
      updated.classList.toggle('is-stale', when === '尚未同步');
      banner.hidden = !data.degraded;
      if (data.degraded) banner.textContent = '上游暂时不可用，当前展示的是最近一份快照，可能不是最新。';
    } catch (error) {
      list.innerHTML = `<div class="hs-empty"><strong>热榜暂时读不到</strong>${escapeHtml(error.message)}</div>`;
      updated.querySelector('span').textContent = '读取失败';
      updated.classList.add('is-stale');
    }
  }

  chips?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-platform]');
    if (!button) return;
    state.platform = button.dataset.platform || '';
    load();
  });

  search?.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.q = search.value.trim();
      load();
    }, 250);
  });

  list?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-create]');
    if (!button) return;
    const title = button.dataset.create || '';
    const url = button.dataset.url || '';
    const input = document.querySelector('#workbench-topic');
    if (!input) return;
    input.value = `围绕这个热点写一篇公众号：${title}（来源：${url}）`;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    window.AppNav?.setActiveView?.('workbench', true);
    document.querySelector('#start-workbench')?.click();
  });

  async function ensureLoaded() {
    if (state.loaded) return;
    state.loaded = true;
    await load();
  }


  // 导航兜底：静态锚点可能被侧边栏重建吞掉，这里保证 tab 一定在「公众号创作」上面
  function ensureNavItem() {
    const nav = document.querySelector('.app-tabs');
    if (!nav || nav.querySelector('[data-view="hotspots"]')) return;
    const link = document.createElement('a');
    link.dataset.view = 'hotspots';
    link.href = '/hotspots';
    link.innerHTML = '<svg class="tab-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 17l5-5 4 3 5-7 4 5"/><path d="M3 21h18"/></svg><span>热点广场</span>';
    const anchor = nav.querySelector('a[href="/workbench"]');
    if (anchor) nav.insertBefore(link, anchor); else nav.appendChild(link);
  }
  ensureNavItem();
  new MutationObserver(ensureNavItem).observe(document.querySelector('.app-tabs') || document.body, { childList: true });

  window.HotspotsView = { ensureLoaded };
  if (!page.hidden) ensureLoaded();
})();
