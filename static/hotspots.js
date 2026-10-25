(() => {
  'use strict';

  const page = document.querySelector('#hotspots');
  if (!page) return;

  const grid = page.querySelector('#hs-grid');
  const chips = page.querySelector('#hs-platforms');
  const search = page.querySelector('#hs-search');
  const updated = page.querySelector('#hs-updated');
  const banner = page.querySelector('#hs-banner');

  const ORDER = ['weibo', 'zhihu', 'douyin', 'toutiao', 'baidu', 'bilibili',
                 'juejin', 'tieba', 'douban', 'v2ex', 'hackernews', 'github'];
  const PAGE = 4;
  const FAV_KEY = 'hotspot:favorites';
  const state = { platform: '', q: '', loaded: false, favoritesOnly: false, rotate: {},
                  items: [], platforms: [], snapshotReady: false };
  let timer = null;
  let loadVersion = 0;
  let chipsKey = null;

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

  async function api(path, options) {
    const response = await fetch(path, { credentials: 'same-origin', ...(options || {}) });
    if (!response.ok) throw new Error(`请求失败（${response.status}）`);
    return response.json();
  }

  // ---- 收藏（只存本地，不入库） ----
  function favorites() {
    try {
      const raw = JSON.parse(localStorage.getItem(FAV_KEY) || '[]');
      return Array.isArray(raw) ? raw : [];
    } catch { return []; }
  }
  function isFavorite(item) {
    return favorites().some((row) => row.url === item.url);
  }
  function toggleFavorite(item) {
    const rows = favorites();
    const index = rows.findIndex((row) => row.url === item.url);
    if (index >= 0) {
      rows.splice(index, 1);
      localStorage.setItem(FAV_KEY, JSON.stringify(rows));
      return false;
    }
    rows.unshift({ title: item.title, url: item.url, platform: item.platform,
                   platform_zh: item.platform_zh, hot: item.hot, rank: item.rank });
    localStorage.setItem(FAV_KEY, JSON.stringify(rows.slice(0, 200)));
    return true;
  }

  function group(items) {
    const buckets = new Map();
    for (const item of items) {
      if (!buckets.has(item.platform)) buckets.set(item.platform, []);
      buckets.get(item.platform).push(item);
    }
    const known = ORDER.filter((pid) => buckets.has(pid));
    const extra = [...buckets.keys()].filter((pid) => !ORDER.includes(pid));
    return [...known, ...extra].map((pid) => ({ platform: pid, items: buckets.get(pid) }));
  }

  function renderChips() {
    const total = state.platforms.reduce((sum, item) => sum + (item.count || 0), 0);
    const favCount = favorites().length;
    const rows = [{ id: '', name: '全部', count: total, ok: true }, ...state.platforms];
    const fav = favCount
      ? `<button type="button" class="hs-chip hs-chip-fav" data-fav-view="1" aria-pressed="${state.favoritesOnly}">收藏 ${favCount}</button>`
      : '';
    const key = JSON.stringify([rows, favCount]);
    if (key === chipsKey) {
      chips.querySelectorAll('[data-platform]').forEach(button => button.setAttribute('aria-pressed', String(!state.favoritesOnly && button.dataset.platform === state.platform)));
      chips.querySelector('[data-fav-view]')?.setAttribute('aria-pressed', String(state.favoritesOnly));
      return;
    }
    chipsKey = key;
    chips.innerHTML = rows.map((item) => `
      <button type="button" class="hs-chip${item.ok === false ? ' is-off' : ''}"
              data-platform="${escapeHtml(item.id)}"
              aria-pressed="${!state.favoritesOnly && item.id === state.platform}">
        ${escapeHtml(item.name)} <span class="hs-chip-count">${item.count || 0}</span>
      </button>`).join('') + fav;
  }

  function itemHtml(item) {
    const meta = item.hot ? item.hot : `热搜 #${item.rank || 0}`;
    const starred = isFavorite(item) ? ' is-on' : '';
    return `
      <li class="hs-item">
        <a class="hs-item-title" href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title)}</a>
        <span class="hs-item-meta">${escapeHtml(meta)}</span>
        <span class="hs-item-tools">
          <button type="button" class="hs-mini" data-copy="${escapeHtml(item.title)}" title="复制标题" aria-label="复制标题：${escapeHtml(item.title)}">复制</button>
          <button type="button" class="hs-mini hs-star${starred}" data-fav="${escapeHtml(item.url)}" title="${starred ? '取消收藏' : '收藏'}" aria-label="${starred ? '取消收藏' : '收藏'}：${escapeHtml(item.title)}" aria-pressed="${!!starred}">★</button>
          <button type="button" class="hs-go" data-create="${escapeHtml(item.title)}" data-url="${escapeHtml(item.url)}">去创作</button>
        </span>
      </li>`;
  }

  function cardHtml(rows, options) {
    const head = rows[0] || {};
    const { offset = 0, pageSize = PAGE, showTools = true, title, subtitle } = options || {};
    const start = rows.length > pageSize ? offset % rows.length : 0;
    const visible = rows.slice(start, start + pageSize);
    if (visible.length < pageSize && rows.length > pageSize) {
      visible.push(...rows.slice(0, pageSize - visible.length));
    }
    const rest = rows.length - visible.length;
    const rotate = showTools && rows.length > pageSize
      ? `<button type="button" class="hs-card-btn" data-rotate="${escapeHtml(head.platform || '')}">换一批</button>` : '';
    const refresh = showTools && head.platform
      ? `<button type="button" class="hs-card-btn" data-refresh="${escapeHtml(head.platform)}">刷新</button>` : '';
    return `
      <section class="hs-card" data-platform="${escapeHtml(head.platform || '')}">
        <header class="hs-card-head">
          <span class="hs-dot hs-dot-${escapeHtml(head.platform || '')}" aria-hidden="true"></span>
          <h2>${showTools && head.platform ? `<button type="button" class="hs-platform-open" data-open-platform="${escapeHtml(head.platform)}" title="查看此平台更多热点">${escapeHtml(title || head.platform_zh || head.platform)}</button>` : escapeHtml(title || head.platform_zh || head.platform || '')}</h2>
          <span class="hs-card-count">${rows.length} 条</span>
        </header>
        <ol class="hs-card-list">${visible.map(itemHtml).join('')}</ol>
        <footer class="hs-card-foot">
          <span>${subtitle || (rest > 0 ? `还有 ${rest} 条` : '')}</span>
          <span class="hs-card-tools">${rotate}${refresh}</span>
        </footer>
      </section>`;
  }

  function renderGrid() {
    if (state.favoritesOnly) {
      const rows = favorites();
      if (!rows.length) {
        grid.innerHTML = `<div class="hs-empty"><strong>还没有收藏</strong>把常看的热点点上 ★，就会出现在这里。</div>`;
        return;
      }
      grid.innerHTML = cardHtml(rows, {
        pageSize: 30, showTools: false, title: '我的收藏',
        subtitle: `${rows.length} 条 · 只存在这台设备上`,
      });
      return;
    }
    const needle = state.q.toLocaleLowerCase();
    const filtered = state.items.filter(item => (!state.platform || item.platform === state.platform) && (!needle || `${item.title || ''} ${item.excerpt || ''}`.toLocaleLowerCase().includes(needle)));
    const groups = group(filtered);
    if (!groups.length) {
      grid.innerHTML = `<div class="hs-empty"><strong>这个筛选下没有热点</strong>换个平台，或清空搜索词。</div>`;
      return;
    }
    grid.innerHTML = groups.map((entry) => cardHtml(entry.items, {
      offset: state.rotate[entry.platform] || 0,
      pageSize: state.platform ? 30 : PAGE,
      showTools: !state.platform,
    })).join('');
  }

  function skeleton() {
    grid.innerHTML = Array.from({ length: 6 }, () => '<div class="hs-skeleton"></div>').join('');
  }

  async function load() {
    const version = ++loadVersion;
    if (!state.snapshotReady) skeleton();
    grid.setAttribute('aria-busy', 'true');
    const params = new URLSearchParams({ limit: '400' });
    try {
      const data = await api(`/api/hotspots?${params.toString()}`);
      if (version !== loadVersion) return;
      state.snapshotReady = true;
      state.items = data.items || [];
      state.platforms = data.platforms || [];
      renderChips();
      renderGrid();
      const when = formatTime(data.updated_at);
      updated.querySelector('span').textContent = `${state.platforms.length} 个平台 · ${when === '尚未同步' ? when : `更新于 ${when}`}`;
      updated.classList.toggle('is-stale', when === '尚未同步');
      banner.hidden = !data.degraded;
      if (data.degraded) banner.textContent = '上游暂时不可用，当前展示的是最近一份快照，可能不是最新。';
    } catch (error) {
      if (version !== loadVersion) return;
      if (state.snapshotReady) {
        banner.hidden = false;
        banner.textContent = '刷新暂时失败，已保留当前热点，请稍后重试。';
        return;
      }
      grid.innerHTML = `<div class="hs-empty"><strong>热榜暂时读不到</strong>${escapeHtml(error.message)}<br><button type="button" class="hs-card-btn" data-retry>重新加载</button></div>`;
      updated.querySelector('span').textContent = '读取失败';
      updated.classList.add('is-stale');
    } finally {
      if (version === loadVersion) grid.setAttribute('aria-busy', 'false');
    }
  }

  chips?.addEventListener('click', (event) => {
    const favView = event.target.closest('[data-fav-view]');
    if (favView) {
      state.favoritesOnly = !state.favoritesOnly;
      state.platform = '';
      state.q = '';
      if (search) search.value = '';
      renderChips();
      renderGrid();
      return;
    }
    const button = event.target.closest('[data-platform]');
    if (!button) return;
    state.favoritesOnly = false;
    state.platform = button.dataset.platform || '';
    renderChips();
    renderGrid();
  });

  search?.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.q = search.value.trim();
      state.favoritesOnly = false;
      renderChips();
      renderGrid();
    }, 250);
  });

  grid?.addEventListener('click', async (event) => {
    if(event.target.closest('[data-retry]')) {await load();return;}
    const openPlatform=event.target.closest('[data-open-platform]');
    if(openPlatform) {state.platform=openPlatform.dataset.openPlatform;state.favoritesOnly=false;renderChips();renderGrid();return;}

    const copy = event.target.closest('[data-copy]');
    if (copy) {
      try {
        await navigator.clipboard.writeText(copy.dataset.copy || '');
        copy.textContent = '已复制';
      } catch {
        copy.textContent = '失败';
      }
      setTimeout(() => { copy.textContent = '复制'; }, 1200);
      return;
    }

    const fav = event.target.closest('[data-fav]');
    if (fav) {
      const url = fav.dataset.fav;
      const row = state.items.find((item) => item.url === url)
        || favorites().find((item) => item.url === url);
      if (!row) return;
      const added = toggleFavorite(row);
      fav.classList.toggle('is-on', added);
      fav.setAttribute('aria-pressed', String(added));
      fav.title=added?'取消收藏':'收藏';
      fav.setAttribute('aria-label',`${added?'取消收藏':'收藏'}：${row.title}`);
      renderChips();
      if (state.favoritesOnly) renderGrid();
      return;
    }

    const rotate = event.target.closest('[data-rotate]');
    if (rotate) {
      const platform = rotate.dataset.rotate;
      state.rotate[platform] = (state.rotate[platform] || 0) + PAGE;
      renderGrid();
      return;
    }

    const refresh = event.target.closest('[data-refresh]');
    if (refresh) {
      const platform = refresh.dataset.refresh;
      refresh.textContent = '刷新中…';
      refresh.disabled = true;
      try {
        const result = await api(`/api/hotspots/refresh?platform=${encodeURIComponent(platform)}`,
                                { method: 'POST' });
        if (result.status === 'throttled') {
          refresh.textContent = `${result.retry_after}s 后再试`;
        } else {
          refresh.textContent = '已刷新';
          await load();
        }
      } catch {
        refresh.textContent = '刷新失败';
      }
      setTimeout(() => { refresh.textContent = '刷新'; refresh.disabled = false; }, 2200);
      return;
    }

    const create = event.target.closest('[data-create]');
    if (create) {
      const title = create.dataset.create || '';
      const url = create.dataset.url || '';
      const input = document.querySelector('#workbench-topic');
      if (!input) return;
      input.value = `围绕这个热点写一篇公众号：${title}（来源：${url}）`;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      window.AppNav?.setActiveView?.('workbench', true);
      document.querySelector('#start-workbench')?.click();
    }
  });

  async function ensureLoaded() {
    if (state.loaded) return;
    state.loaded = true;
    await load();
  }

  window.HotspotsView = { ensureLoaded };
  if (!page.hidden) ensureLoaded();
})();
