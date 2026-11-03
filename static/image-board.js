/* 低粉爆图：封面优先的图片榜。
   只读本地快照 API，浏览时不触达计费上游；封面走 /api/image-board/cover 代理，
   因为微信图片有防盗链，浏览器直连会变成灰块。 */
(() => {
  const root = document.querySelector('#image-board');
  if (!root) return;

  const state = { scope: 'all', type: '', q: '', sort: 'read', date: '', loaded: false, loading: false, reloadPending: false };
  const $ = (sel) => root.querySelector(sel);

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g,
    (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  const fmt = (value) => {
    const n = Number(value) || 0;
    if (n >= 100000) return '10万+';
    if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + '万';
    return n.toLocaleString('en-US');
  };

  function renderTracks(categories, total) {
    const chips = [{ name: '', label: '全部', count: total }]
      .concat((categories || []).map((item) => ({ name: item.name, label: item.name, count: item.count })));
    $('#ib-tracks').innerHTML = chips.map((chip) => {
      const active = (state.type || '') === chip.name;
      return `<button type="button" class="ib-track${active ? ' is-active' : ''}"
        data-type="${esc(chip.name)}" title="${esc(chip.label)} · ${chip.count} 篇"
        aria-pressed="${active}">${esc(chip.label)}<n>${chip.count}</n></button>`;
    }).join('');
  }

  function cardHtml(item, index) {
    const rank = index + 1;
    const cover = item.cover_url
      ? `<img src="${esc(item.cover_url)}" alt="" loading="lazy" decoding="async"
             data-fallback="${esc((item.title || '图').slice(0, 2))}">`
      : `<span class="ib-fallback">${esc((item.title || '图').slice(0, 2))}</span>`;
    const low = item.lowfans;
    const boost = low && low.boost_ratio
      ? `<span class="ib-boost">低粉 ${Number(low.boost_ratio).toFixed(1).replace(/\.0$/, '')}×</span>`
      : '';
    const facts = [
      `<em>${item.image_num || 0} 图</em>`,
      `<em>${item.word_num || 0} 字</em>`,
      item.is_fallback ? `<em>补充 · ${esc(item.stat_date)}</em>` : '',
      item.wx_type ? `<em>${esc(item.wx_type)}</em>` : '',
      low ? `<em class="is-warm">${esc(low.wx_name || '')}</em>` : '',
    ].filter(Boolean).join('');

    return `<article class="ib-card">
      <div class="ib-cover">
        ${cover}
        <span class="ib-rank${rank <= 3 ? ' is-top' : ''}">${rank}</span>
        <span class="ib-kind">${item.image_first ? '图为主' : '图文'}</span>
        <div class="ib-onimg">
          <span class="ib-read">${fmt(item.read_num)}<small>阅读</small></span>
          <span class="ib-share">${fmt(item.share_num)} 分享${boost ? ' ' + boost : ''}</span>
        </div>
      </div>
      <div class="ib-body">
        <a class="ib-title" href="${esc(item.art_url)}" target="_blank"
           rel="noopener noreferrer">${esc(item.title || '无标题')}</a>
        <p class="ib-sub">${esc(item.excerpt || '')}</p>
        <div class="ib-facts">${facts}</div>
        <div class="ib-actions">
          <a class="ib-act" href="${esc(item.art_url)}" target="_blank"
             rel="noopener noreferrer">看原文</a>
          ${low ? '<a class="ib-act is-primary" href="/lowfans">看同榜</a>' : ''}
        </div>
      </div>
    </article>`;
  }

  function renderPreview(data) {
    const grid = $('#ib-grid');
    grid.className = '';
    const rows = (data.items || []).map((item) => `<article class="ib-card">
      <div class="ib-cover">${item.cover_url
        ? `<img src="${esc(item.cover_url)}" alt="" loading="lazy" decoding="async" data-fallback="${esc((item.title_preview || '图').slice(0, 2))}">`
        : `<span class="ib-fallback">${esc((item.title_preview || '图').slice(0, 2))}</span>`}
        <span class="ib-rank${item.rank_no <= 3 ? ' is-top' : ''}">${item.rank_no}</span></div>
      <div class="ib-body"><b class="ib-title">${esc(item.title_preview || '')}</b>
        <div class="ib-facts"><em>${esc(item.wx_type || '')}</em></div></div></article>`).join('');
    grid.innerHTML = `<div class="vi-preview"><div class="ib-grid">${rows}</div>
      <div class="vi-lock"><strong>解锁完整榜单、阅读数据和原文</strong>
      <p>低粉爆文与低粉爆图共用权益。开启后才开始免费试用计时，未开启不会扣费；筛选、排序和搜索在开启后可用。</p>
      <button type="button" class="vi-primary" data-viral-insights-open>查看权益</button></div></div>`;
    setupCovers(grid);
  }

  function renderList(data) {
    if (data.preview) { renderPreview(data); return; }
    const items = data.items || [];
    const grid = $('#ib-grid');
    if (!items.length) {
      grid.innerHTML = `<div class="ib-empty">
        <strong>当前范围没有内容</strong>
        <p>${state.q
          ? '换个关键词，或切到「全部贴图」看看。'
          : '这一范围今天没有符合条件的贴图，换一个范围或赛道试试。'}</p>
      </div>`;
      return;
    }
    grid.className = '';
    grid.innerHTML = `<div class="ib-grid">${items.map(cardHtml).join('')}</div>`;
    setupCovers(grid);
  }

  function setupCovers(grid) {
    grid.querySelectorAll('.ib-cover img').forEach((img) => {
      const done = () => img.classList.add('is-ready');
      const fail = () => {
        const span = document.createElement('span');
        span.className = 'ib-fallback';
        span.textContent = img.dataset.fallback || '图';
        img.replaceWith(span);
      };
      if (img.complete && img.naturalWidth > 0) done();
      else {
        img.addEventListener('load', done, { once: true });
        img.addEventListener('error', fail, { once: true });
      }
    });
  }

  function renderMeta(data) {
    const sync = data.last_sync || {};
    $('#ib-stamp').innerHTML = data.stat_date
      ? `<span>榜单日期 <b>${esc(data.stat_date)}</b></span>`
      : '<span>正在读取…</span>';
    const total = Number(data.total) || 0;
    const pool = data.fallback_count ? `（当日 ${data.primary_count} 条，历史补充 ${data.fallback_count} 条）` : '';
    $('#ib-tail').textContent = total ? `${data.preview ? '预览 ' : ''}${total} 条 · ${data.stat_date || ''}${pool}` : '暂无数据';
    const scopeCount = Number(data.counts?.[state.scope]) || total;
    renderTracks(data.categories, scopeCount);
    const dates = data.dates || [];
    const select = $('#ib-date');
    select.hidden = dates.length <= 1;
    select.innerHTML = dates.map((day) =>
      `<option value="${esc(day)}"${day === (state.date || data.stat_date) ? ' selected' : ''}>${esc(day)}</option>`
    ).join('');
  }

  function skeleton(count = 8) {
    const grid = $('#ib-grid');
    grid.className = '';
    grid.innerHTML = `<div class="ib-grid">${Array.from({ length: count }, () =>
      '<div class="ib-card ib-skeleton"><div class="ib-cover"></div><div class="ib-body">'
      + '<span style="display:block;height:12px;width:82%;border-radius:4px;background:#eef3ef"></span>'
      + '</div></div>').join('')}</div>`;
  }

  async function load() {
    if (state.loading) { state.reloadPending = true; return; }
    state.loading = true;
    skeleton();
    const params = new URLSearchParams({ scope: state.scope, sort: state.sort });
    if (state.type) params.set('wx_type', state.type);
    if (state.q) params.set('q', state.q);
    if (state.date) params.set('date', state.date);
    try {
      const response = await fetch('/api/image-board?' + params.toString(), { credentials: 'same-origin' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      root.querySelectorAll('#ib-search, #ib-sort, #ib-date').forEach(el => { el.disabled = !!data.preview; });
      renderMeta(data);
      renderList(data);
      root.querySelectorAll('#ib-tracks button').forEach(el => { el.disabled = !!data.preview; });
      state.loaded = true;
      if (data.degraded) {
        const age = data.freshness?.last_success_at
          ? `最近成功更新 ${new Date(data.freshness.last_success_at).toLocaleString('zh-CN', { hour12: false })}`
          : '尚无成功同步记录';
        $('#ib-stamp').innerHTML = `<span class="is-warn">${esc(data.stat_date ? '快照 ' + data.stat_date : '')} · ${esc(age)}</span>`;
        if (data.reason) $('#ib-tail').textContent += ` · ${data.reason}`;
      }
    } catch (error) {
      $('#ib-grid').className = '';
      $('#ib-grid').innerHTML = `<div class="ib-empty"><strong>榜单读取失败</strong>
        <p>${esc(error.message)}，请稍后重试。</p></div>`;
      $('#ib-stamp').innerHTML = '<span>读取失败</span>';
    } finally {
      state.loading = false;
      if (state.reloadPending) { state.reloadPending = false; load(); }
    }
  }

  /* ---------------------------------------------------------------- 事件 */
  $('#ib-tracks').addEventListener('click', (event) => {
    const button = event.target.closest('[data-type]');
    if (!button) return;
    state.type = button.dataset.type;
    load();
  });

  $('#ib-sort').addEventListener('change', (event) => {
    state.sort = event.target.value;
    load();
  });

  $('#ib-date').addEventListener('change', (event) => {
    state.date = event.target.value;
    load();
  });

  let searchTimer = 0;
  $('#ib-search').addEventListener('input', (event) => {
    clearTimeout(searchTimer);
    const next = event.target.value.trim();
    searchTimer = setTimeout(() => {
      if (next === state.q) return;
      state.q = next;
      // 搜索时保留赛道筛选会让「摄影 + 裁员」这类组合直接空列表，所以清掉。
      if (state.q && state.type) state.type = '';
      load();
    }, 300);
  });

  window.ImageBoardView = {
    ensureLoaded() {
      if (!state.loaded) load();
    },
    reload: () => load(),
  };
})();
