/* 低分爆图：封面优先的图片榜。
   只读本地快照 API，浏览时不触达计费上游；封面走 /api/image-board/cover 代理，
   因为微信图片有防盗链，浏览器直连会变成灰块。 */
(() => {
  const root = document.querySelector('#image-board');
  if (!root) return;

  const state = { scope: 'image', type: '', q: '', sort: 'read', date: '', loaded: false, loading: false };
  const $ = (sel) => root.querySelector(sel);

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g,
    (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  const fmt = (value) => {
    const n = Number(value) || 0;
    if (n >= 100000) return '10万+';
    if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + '万';
    return n.toLocaleString('en-US');
  };

  const SCOPES = {
    image: '图为主',
    lowfans: '已匹配低粉',
    all: '全部贴图',
  };

  function renderScopes(counts) {
    $('#ib-scopes').innerHTML = Object.entries(SCOPES).map(([key, label]) => {
      const active = state.scope === key;
      const count = Number(counts?.[key]) || 0;
      return `<button type="button" class="ib-scope" data-scope="${key}" role="tab"
        aria-selected="${active}">${label}<n>${count}</n></button>`;
    }).join('');
  }

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

  function renderList(data) {
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

  function renderNote(data) {
    const note = $('#ib-note');
    if (state.scope === 'image') {
      note.innerHTML = `<b>图为主</b> = 正文不超过 ${data.image_first_max_words || 100} 字、无视频、至少 1 张图。`
        + '这是按字段做的规则筛选，不等同于逐篇人工确认。';
    } else if (state.scope === 'lowfans') {
      note.innerHTML = '<b>已匹配低粉</b> 只表示文章标识出现在当前已同步的低粉爆文快照里；'
        + '没匹配到不代表不是低粉号，只代表不在已采集的样本中。';
    } else {
      note.innerHTML = '<b>全部贴图</b> 来自资源库 content_type=book，里面混有新闻和普通图文，'
        + '所以「图为主」单独作为一个范围。封面由工作台代取，原文仍在微信。';
    }
  }

  function renderMeta(data) {
    const sync = data.last_sync || {};
    $('#ib-stamp').innerHTML = data.stat_date
      ? `<span>榜单日期 <b>${esc(data.stat_date)}</b></span>`
      : '<span>正在读取…</span>';
    const total = Number(data.total) || 0;
    $('#ib-tail').textContent = total ? `${total} 条 · ${data.stat_date || ''}` : '暂无数据';
    renderScopes(data.counts);
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
    if (state.loading) return;
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
      renderMeta(data);
      renderNote(data);
      renderList(data);
      state.loaded = true;
      if (data.degraded) $('#ib-tail').textContent = data.reason || '暂时没有数据';
    } catch (error) {
      $('#ib-grid').className = '';
      $('#ib-grid').innerHTML = `<div class="ib-empty"><strong>榜单读取失败</strong>
        <p>${esc(error.message)}，请稍后重试。</p></div>`;
      $('#ib-stamp').innerHTML = '<span>读取失败</span>';
    } finally {
      state.loading = false;
    }
  }

  /* ---------------------------------------------------------------- 事件 */
  $('#ib-scopes').addEventListener('click', (event) => {
    const button = event.target.closest('[data-scope]');
    if (!button || button.dataset.scope === state.scope) return;
    state.scope = button.dataset.scope;
    state.type = '';
    load();
  });

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
  };
})();
