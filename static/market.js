(() => {
  'use strict';

  const list = document.querySelector('#market-list');
  const more = document.querySelector('#market-more');
  const countEl = document.querySelector('#market-count');
  const rail = document.querySelector('#market-categories');
  const seg = document.querySelector('#market-sort');
  const input = document.querySelector('#market-search-input');
  const featuredWrap = document.querySelector('#market-featured');
  const featuredSection = document.querySelector('#market-featured-section');
  const metaEls = {
    count: document.querySelector('#meta-count'),
    repos: document.querySelector('#meta-repos'),
    official: document.querySelector('#meta-official'),
    updated: document.querySelector('#meta-updated'),
  };
  const adminToggle = document.querySelector('#market-admin-toggle');
  const adminPanel = document.querySelector('#market-admin');
  let isAdmin = false;
  let pins = [];

  const state = { q: '', category: '', sort: 'stars', page: 1, pageSize: 24, pages: 1, total: 0 };

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));

  const starIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="m12 3 2.6 5.7 6.4.6-4.8 4.2 1.4 6.5L12 16.9 6.4 20l1.4-6.5L3 9.3l6.4-.6z"/></svg>';
  const chevron = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg>';

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      throw new Error(detail.slice(0, 160) || `请求失败（${response.status}）`);
    }
    return response.json();
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString('en-US');
  }

  function formatWhen(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value || '');
    return date.toLocaleString('zh-CN', {
      timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    });
  }

  function title(row) {
    return row.name_zh || row.name || '';
  }

  function description(row) {
    return row.description_zh || row.description || '';
  }

  function renderRow(row) {
    const badges = [];
    if (row.official) badges.push('<span class="market-badge official">官方</span>');
    if (row.manual) badges.push('<span class="market-badge manual">手工收录</span>');
    if (row.featured) badges.push(`<span class="market-badge">精选 ${row.pin_rank ?? ''}</span>`);
    const stars = row.manual && !row.stars ? '—' : formatNumber(row.stars);
    const adminActions = isAdmin ? `
      <div class="admin-actions">
        <button type="button" data-pin="${escapeHtml(row.id)}" class="${row.featured ? 'on' : ''}">${row.featured ? '取消精选' : '设为精选'}</button>
        <button type="button" data-hide="${escapeHtml(row.id)}">隐藏</button>
      </div>` : '';
    return `
      <a class="market-row" href="${escapeHtml(row.url)}" target="_blank" rel="noopener noreferrer">
        <div>
          <div class="titleline">
            <span class="name">${escapeHtml(title(row))}</span>
            ${badges.join('')}
          </div>
          <p class="desc" title="${escapeHtml(description(row))}">${escapeHtml(description(row))}</p>
          <div class="meta">
            <span>${escapeHtml(row.repo)}${row.path ? ` · ${escapeHtml(row.path)}` : ''}</span>
            <span>${row.manual ? `手工添加于 ${escapeHtml(row.added_at || '')}` : `收录于 ${escapeHtml((row.added_at || '').slice(5))}`}</span>
          </div>
          ${adminActions}
        </div>
        <div class="side">
          <span class="stars">${starIcon}${stars}</span>
          <span class="cat">${escapeHtml(row.category_zh || '其他')}</span>
        </div>
        <span class="go">前往 GitHub ${chevron}</span>
      </a>`;
  }

  function renderFeatured(rows) {
    if (!rows.length) {
      featuredSection.hidden = true;
      return;
    }
    featuredSection.hidden = false;
    featuredWrap.innerHTML = rows.map((row, index) => `
      <a class="market-fcard" href="${escapeHtml(row.url)}" target="_blank" rel="noopener noreferrer">
        <span class="tag">精选 ${String(index + 1).padStart(2, '0')}</span>
        <strong>${escapeHtml(title(row))}</strong>
        <p>${escapeHtml(description(row))}</p>
        <span class="src">${escapeHtml(row.repo)}</span>
      </a>`).join('');
  }

  function renderCategories(categories) {
    const all = { slug: '', name: '全部', count: categories.reduce((sum, item) => sum + item.count, 0) };
    rail.innerHTML = [all, ...categories].map((item) => `
      <li><a href="#" data-category="${escapeHtml(item.slug)}" class="${item.slug === state.category ? 'on' : ''}">
        ${escapeHtml(item.name)}<span class="n">${formatNumber(item.count)}</span></a></li>`).join('');
  }

  async function loadMeta() {
    try {
      const data = await api('/api/market/meta');
      metaEls.count.textContent = formatNumber(data.count);
      metaEls.repos.textContent = formatNumber(data.repos);
      metaEls.official.textContent = formatNumber(data.official);
      metaEls.updated.textContent = data.generated_at
        ? `数据更新于 ${formatWhen(data.generated_at)}`
        : '尚未同步';
      renderCategories(data.categories || []);
    } catch (error) {
      metaEls.updated.textContent = '尚未同步';
      console.warn(error);
    }
  }

  async function loadFeatured() {
    try {
      const data = await api('/api/market/skills?featured=true');
      pins = data.items || [];
      renderFeatured(pins.slice(0, 3));
    } catch (error) {
      console.warn(error);
    }
  }

  function skeleton() {
    list.innerHTML = '<div class="market-loading">正在读取索引…</div>';
  }

  async function loadList({ append = false } = {}) {
    if (!append) skeleton();
    const params = new URLSearchParams({
      q: state.q, category: state.category, sort: state.sort,
      page: String(state.page), page_size: String(state.pageSize),
    });
    let data;
    try {
      data = await api(`/api/market/skills?${params.toString()}`);
    } catch (error) {
      list.innerHTML = `<div class="market-empty"><strong>索引暂时读不到</strong>${escapeHtml(error.message)}<button type="button" data-market-retry>重新加载</button></div>`;
      more.hidden = true;
      return;
    }
    state.total = data.total;
    state.pages = data.pages || 1;
    countEl.textContent = formatNumber(data.total);
    const html = (data.items || []).map(renderRow).join('');
    if (append) list.insertAdjacentHTML('beforeend', html);
    else list.innerHTML = html;
    if (!data.total) {
      list.innerHTML = `<div class="market-empty"><strong>没有匹配的 skill</strong>换个关键词，或切回「全部」分类看看。</div>`;
    }
    more.hidden = state.page >= state.pages;
  }

  function refresh(reset = true) {
    if (reset) state.page = 1;
    loadList();
  }

  let timer = null;
  input?.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.q = input.value.trim();
      refresh();
    }, 250);
  });

  seg?.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-sort]');
    if (!button) return;
    state.sort = button.dataset.sort;
    seg.querySelectorAll('button').forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
    refresh();
  });

  rail?.addEventListener('click', (event) => {
    const link = event.target.closest('a[data-category]');
    if (!link) return;
    event.preventDefault();
    state.category = link.dataset.category;
    rail.querySelectorAll('a').forEach((item) => item.classList.toggle('on', item === link));
    refresh();
  });

  more?.addEventListener('click', () => {
    state.page += 1;
    loadList({ append: true });
  });

  // ---------- 管理端 ----------
  async function loadSession() {
    try {
      const data = await api('/api/auth/me');
      isAdmin = data?.user?.role === 'admin';
    } catch { isAdmin = false; }
    if (adminToggle) adminToggle.hidden = !isAdmin;
  }

  adminToggle?.addEventListener('click', () => adminPanel.classList.add('open'));
  adminPanel?.addEventListener('click', (event) => {
    if (event.target.closest('[data-close]')) adminPanel.classList.remove('open');
  });

  list?.addEventListener('click', async (event) => {
    const pinButton = event.target.closest('[data-pin]');
    const hideButton = event.target.closest('[data-hide]');
    if ((pinButton || hideButton) && event.currentTarget.contains(event.target)) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (pinButton) {
      const id = pinButton.dataset.pin;
      const exists = pins.some((row) => row.id === id);
      const next = exists
        ? pins.filter((row) => row.id !== id)
        : [...pins, { id }];
      const payload = next.map((row, index) => ({ id: row.id, rank: index + 1, note: row.pin_note || '' }));
      try {
        await api('/api/admin/market/pins', { method: 'POST', body: JSON.stringify({ pins: payload }) });
        await Promise.all([loadFeatured(), loadList()]);
      } catch (error) { alert(`设置精选失败：${error.message}`); }
    }
    if (hideButton) {
      const id = hideButton.dataset.hide;
      try {
        await api('/api/admin/market/hidden', { method: 'POST', body: JSON.stringify({ hidden: [id] }) });
        await Promise.all([loadFeatured(), loadList()]);
      } catch (error) { alert(`隐藏失败：${error.message}`); }
    }
  });

  document.querySelector('#market-add-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const payload = {
      name: form.name.value.trim(),
      repo: form.repo.value.trim(),
      path: form.path.value.trim(),
      category: form.category.value,
      description: form.description.value.trim(),
      stars: Number(form.stars.value || 0),
    };
    try {
      await api('/api/admin/market/items', { method: 'POST', body: JSON.stringify(payload) });
      form.reset();
      await Promise.all([loadMeta(), loadList()]);
    } catch (error) { alert(`添加失败：${error.message}`); }
  });

  // 工作台里的一个视图：第一次切到「AI 超市」时才拉数据，切走不销毁。
  let booted = false;
  async function ensureLoaded() {
    if (booted) return;
    booted = true;
    await loadSession();
    await loadMeta();
    await loadFeatured();
    await loadList();
  }
  list.addEventListener('click', event => { if (event.target.closest('[data-market-retry]')) { booted = false; ensureLoaded(); } });
  window.MarketView = { ensureLoaded };
  const host = document.querySelector('#market, #market-main');
  if (host && !host.hidden) ensureLoaded();
})();
