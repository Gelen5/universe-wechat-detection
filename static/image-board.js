/* 低粉爆图：封面优先的图片榜。
   只读本地快照 API，浏览时不触达计费上游；封面走 /api/image-board/cover 代理，
   因为微信图片有防盗链，浏览器直连会变成灰块。 */
(() => {
  const root = document.querySelector('#image-board');
  if (!root) return;

  /* 分批加载：offset 是已消费条数（不是页码），hasMore 由后端给出；
     loadingMore / seq / controller 用来防止重复请求和旧响应覆盖新筛选。 */
  const PAGE_SIZE = 40;
  const state = {
    scope: 'all', type: '', q: '', sort: 'read', date: '', loaded: false, loading: false, reloadPending: false,
    offset: 0, hasMore: true, loadingMore: false, seq: 0, controller: null, moreController: null, observer: null,
  };
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
    // rank_no 是后端给的全量排名（第 2 页是 41-80），不能按页内序号重排。
    const rank = Number(item.rank_no) || (index + 1);
    const cover = item.cover_url
      ? `<img src="${esc(item.cover_url)}" alt="" loading="lazy" decoding="async"
             data-fallback="${esc((item.title || '图').slice(0, 2))}">`
      : `<span class="ib-fallback">${esc((item.title || '图').slice(0, 2))}</span>`;
    const canExtract = /^https:\/\/mp\.weixin\.qq\.com\/s(?:\/|\?)/i.test(item.art_url || '');
    const facts = [
      `<em>${item.image_num || 0} 图</em>`,
      `<em>${item.word_num || 0} 字</em>`,
      item.wx_type ? `<em>${esc(item.wx_type)}</em>` : '',
    ].filter(Boolean).join('');

    return `<article class="ib-card">
      <div class="ib-cover">
        ${cover}
        <span class="ib-rank${rank <= 3 ? ' is-top' : ''}">${rank}</span>
        <span class="ib-kind">${item.image_first ? '图为主' : '图文'}</span>
        <div class="ib-onimg">
          <span class="ib-read">${fmt(item.read_num)}<small>阅读</small></span>
          <span class="ib-share">${fmt(item.share_num)} 分享</span>
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
          ${canExtract ? `<button type="button" class="ib-act ib-extract" data-ib-extract="${esc(item.art_url)}">一键提取并复刻 →</button>` : ''}
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
      <p>低粉爆文、低粉爆图和选题灵感库共用权益。开启后才开始免费试用计时，未开启不会扣费；筛选、排序和搜索在开启后可用。</p>
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

  /* ---- 分批加载 ---------------------------------------------------------
     首屏 40 条一次性渲染；接近底部时按 offset 追加下一页。追加只对新节点跑
     setupCovers，已加载的封面不会重建、不会闪。sentinel 放在 .ib-grid 外面，
     避免成为 grid 的一个格子。 */
  function sentinelNode() { return $('#ib-grid [data-ib-more]'); }

  function setSentinel(html) {
    const node = sentinelNode();
    if (node) node.innerHTML = html;
    return node;
  }

  function moreButton(label) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.style.cssText = 'min-height:44px;padding:0 20px;border:1px solid #cfe0d5;border-radius:999px;'
      + 'background:#fff;color:#286146;font-size:13px;cursor:pointer;';
    button.addEventListener('click', () => loadMore());
    return button;
  }

  function watchSentinel() {
    const node = sentinelNode();
    if (!node) return;
    // 自动加载之外始终保留手动入口，避免浏览器观察器未触发时卡在列表底部。
    if (!node.querySelector('button')) node.append(moreButton('加载更多'));
    if (!('IntersectionObserver' in window)) return;
    if (!state.observer) {
      state.observer = new IntersectionObserver((entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadMore();
      }, { rootMargin: '600px 0px' });
    }
    // 追加后重新 observe：sentinel 可能仍在视口内，需要再触发一次才能继续填满。
    state.observer.disconnect();
    state.observer.observe(node);
  }

  function armSentinel() {
    const host = $('#ib-grid');
    if (!host || state.preview || !state.hasMore) return;
    let node = host.querySelector('[data-ib-more]');
    if (!node) {
      node = document.createElement('div');
      node.className = 'ib-more';
      node.setAttribute('data-ib-more', '');
      node.style.cssText = 'padding:18px 0 6px;text-align:center;color:#5b7466;font-size:13px;';
      host.append(node);
    }
    watchSentinel();
  }

  function hideSentinel() {
    state.observer?.disconnect();
    sentinelNode()?.remove();
  }

  function appendItems(items) {
    const grid = $('#ib-grid .ib-grid');
    if (!grid || !items.length) return;
    const host = document.createElement('div');
    host.innerHTML = items.map((item, index) => cardHtml(item, state.offset + index)).join('');
    const added = [...host.children];
    grid.append(...added);
    added.forEach((node) => setupCovers(node));
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

  function boardParams() {
    const params = new URLSearchParams({ scope: state.scope, sort: state.sort });
    if (state.type) params.set('wx_type', state.type);
    if (state.q) params.set('q', state.q);
    if (state.date) params.set('date', state.date);
    return params;
  }

  /* 首屏 / 切筛选：offset 归零、重建 grid，并作废在途的 loadMore。 */
  async function load() {
    if (state.loading) { state.reloadPending = true; return; }
    state.loading = true;
    const seq = ++state.seq;
    state.controller?.abort();
    state.moreController?.abort();
    const controller = new AbortController();
    state.controller = controller;
    state.offset = 0;
    state.hasMore = true;
    state.loadingMore = false;
    hideSentinel();
    skeleton();
    const params = boardParams();
    params.set('limit', String(PAGE_SIZE));
    params.set('offset', '0');
    try {
      const response = await fetch('/api/image-board?' + params.toString(), { credentials: 'same-origin', signal: controller.signal });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (seq !== state.seq) return;
      state.preview = !!data.preview;
      root.querySelectorAll('#ib-search, #ib-sort, #ib-date').forEach(el => { el.disabled = false; });
      renderMeta(data);
      renderList(data);
      if (state.preview) window.ViralInsightsMembership?.promptPreview();
      const items = data.items || [];
      state.offset = (Number(data.offset) || 0) + items.length;
      // 预览态不分页；has_more 缺失（老响应）按 false 处理，避免无限请求。
      state.hasMore = Boolean(data.has_more) && !state.preview && items.length > 0;
      if (!state.preview) armSentinel();
      state.loaded = true;
      if (data.degraded) {
        const age = data.freshness?.last_success_at
          ? `最近成功更新 ${new Date(data.freshness.last_success_at).toLocaleString('zh-CN', { hour12: false })}`
          : '尚无成功同步记录';
        $('#ib-stamp').innerHTML = `<span class="is-warn">${esc(data.stat_date ? '快照 ' + data.stat_date : '')} · ${esc(age)}</span>`;
        if (data.reason) $('#ib-tail').textContent += ` · ${data.reason}`;
      }
    } catch (error) {
      if (error?.name === 'AbortError' || seq !== state.seq) return;
      $('#ib-grid').className = '';
      $('#ib-grid').innerHTML = `<div class="ib-empty"><strong>榜单读取失败</strong>
        <p>${esc(error.message)}，请稍后重试。</p></div>`;
      $('#ib-stamp').innerHTML = '<span>读取失败</span>';
    } finally {
      if (seq === state.seq) state.loading = false;
      if (state.reloadPending) { state.reloadPending = false; load(); }
    }
  }

  /* 触底追加：只追加新分片，不重建列表；失败在 sentinel 处给「重试」。 */
  async function loadMore() {
    if (state.loading || state.loadingMore || !state.hasMore || state.preview || !state.loaded) return;
    state.loadingMore = true;
    const seq = state.seq;
    state.moreController?.abort();
    const controller = new AbortController();
    state.moreController = controller;
    setSentinel('<span role="status">加载中…</span>');
    const params = boardParams();
    params.set('limit', String(PAGE_SIZE));
    params.set('offset', String(state.offset));
    try {
      const response = await fetch('/api/image-board?' + params.toString(), { credentials: 'same-origin', signal: controller.signal });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      if (seq !== state.seq) return;
      const items = data.items || [];
      appendItems(items);
      state.offset = (Number(data.offset) || 0) + items.length;
      state.hasMore = Boolean(data.has_more) && items.length > 0;
      if (state.hasMore) { setSentinel(''); watchSentinel(); }
      else hideSentinel();
    } catch (error) {
      if (error?.name === 'AbortError' || seq !== state.seq) return;
      state.observer?.disconnect();
      const node = setSentinel('<span role="status">加载失败，请重试。 </span>');
      if (node) node.append(moreButton('重试'));
    } finally {
      if (seq === state.seq) state.loadingMore = false;
    }
  }

  $('#ib-grid').addEventListener('click', (event) => {
    const button = event.target.closest('[data-ib-extract]');
    if (!button) return;
    if (!window.StickerExtract?.startFromArticle) {
      if (typeof showToast === 'function') showToast('提取功能暂不可用，请稍后重试', 'error');
      return;
    }
    window.StickerExtract.startFromArticle(button.dataset.ibExtract);
  });

  /* ---------------------------------------------------------------- 事件 */
  $('#ib-tracks').addEventListener('click', (event) => {
    const button = event.target.closest('[data-type]');
    if (!button) return;
    if (state.preview) { window.ViralInsightsMembership?.open('filter'); return; }
    state.type = button.dataset.type;
    load();
  });

  root.querySelectorAll('#ib-search, #ib-sort, #ib-date').forEach(node => node.addEventListener('pointerdown', event => { if (state.preview) { event.preventDefault(); window.ViralInsightsMembership?.open('filter'); } }));
  root.querySelectorAll('#ib-search, #ib-sort, #ib-date').forEach(node => node?.addEventListener('keydown', event => { if (state.preview && !['Tab', 'Escape', 'Shift'].includes(event.key)) { event.preventDefault(); window.ViralInsightsMembership?.open('filter'); } }));
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
