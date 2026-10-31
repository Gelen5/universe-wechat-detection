/* 低粉爆文榜：只读本地快照，赛道按 wx_type 本地分组。
   上游不支持按赛道过滤，所以「其他」是一个正常赛道（占近四成），不做二次打标。 */
(() => {
  const root = document.querySelector('#lowfans');
  if (!root) return;

  const state = {
    wx_type: '',
    q: '',
    sort: 'burst',
    date: '',
    page: 1,
    pageSize: 50,
    items: [],
    total: 0,
    pages: 1,
    categories: [],
    dates: [],
    statDate: '',
    degraded: false,
    loading: false,
    loaded: false,
  };

  const el = {
    stamp: root.querySelector('#lf-stamp'),
    tracks: root.querySelector('#lf-tracks'),
    list: root.querySelector('#lf-list'),
    search: root.querySelector('#lf-search'),
    sort: root.querySelector('#lf-sort'),
    date: root.querySelector('#lf-date'),
    exportBtn: root.querySelector('#lf-export'),
    note: root.querySelector('#lf-note'),
    tail: root.querySelector('#lf-bar-tail'),
    more: root.querySelector('#lf-more'),
  };

  const esc = (value) => String(value ?? '').replace(/[&<>"']/g,
    (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

  /* 微信把 10 万以上的阅读统一返回成 100001，这里还原成「10万+」。 */
  const fmtNum = (value) => {
    const n = Number(value) || 0;
    if (n <= 0) return '—';
    if (n >= 100000) return '10万+';
    if (n >= 10000) return (n / 10000).toFixed(1).replace(/\.0$/, '') + '万';
    return n.toLocaleString('en-US');
  };

  const fmtBoost = (value) => {
    const n = Number(value) || 0;
    if (n >= 100) return n.toFixed(0);
    if (n >= 10) return n.toFixed(1);
    return n.toFixed(2);
  };

  const fmtTime = (value) => {
    const text = String(value || '');
    const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
    return match ? `${match[2]}-${match[3]} ${match[4]}:${match[5]}` : '';
  };

  function setStatus(text, warn) {
    if (!el.stamp) return;
    el.stamp.innerHTML = `<span class="${warn ? 'is-warn' : ''}">${esc(text)}</span>`;
  }

  function renderTracks() {
    if (!el.tracks) return;
    const total = state.categories.reduce((sum, item) => sum + item.count, 0);
    const chips = [{ name: '', label: '全部', count: total }]
      .concat(state.categories.map((item) => ({ name: item.name, label: item.name, count: item.count })));
    el.tracks.innerHTML = chips.map((chip) => {
      const active = (state.wx_type || '') === (chip.name || '');
      const empty = !chip.count && chip.name;
      return `<button type="button" class="lf-track${empty ? ' is-empty' : ''}" data-track="${esc(chip.name)}"
        aria-pressed="${active}" title="${esc(chip.label)} · ${chip.count} 篇">${esc(chip.label)}<n>${chip.count}</n></button>`;
    }).join('');
  }

  function renderList() {
    if (!el.list) return;
    if (!state.items.length) {
      el.list.innerHTML = `<div class="lf-empty">
        <strong>${state.wx_type ? `「${esc(state.wx_type)}」今天没有入榜文章` : '这批榜单还没有数据'}</strong>
        <p>${state.wx_type
          ? '低粉爆文门槛是阅读 ≥ 1 万、账号基线 ≤ 5000、提升 ≥ 5 倍，长尾赛道每天可能只有个位数。换一个赛道，或直接搜索关键词。'
          : '同步任务每天 09:30 自动跑一次。如果长期为空，检查数据源密钥是否配置。'}</p>
      </div>`;
      if (el.more) el.more.hidden = true;
      return;
    }
    el.list.innerHTML = '<ul class="lf-list">' + state.items.map((item) => {
      const hot = Number(item.boost_ratio) >= 100;
      const type = item.wx_type || '其他';
      return `<li class="lf-row">
        <span class="lf-rank">${item.rank_no}</span>
        <a class="lf-title" href="${esc(item.art_url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a>
        <div class="lf-meta">
          <span class="lf-name">${esc(item.wx_name)}</span>
          <span class="lf-type">${esc(type)}</span>
          <span class="lf-base">阅读基线 ${fmtNum(item.account_read_base)}</span>
          <span>${esc(fmtTime(item.pub_time))}</span>
        </div>
        <div class="lf-metrics">
          <span>阅读 <b>${fmtNum(item.read_num)}</b></span>
          <span>点赞 ${fmtNum(item.like_num)}</span>
          <span>在看 ${fmtNum(item.look_num)}</span>
          <span>分享 ${fmtNum(item.share_num)}</span>
          <span>留言 ${fmtNum(item.comment_num)}</span>
        </div>
        <div class="lf-side">
          <span class="lf-boost${hot ? ' is-hot' : ''}">${fmtBoost(item.boost_ratio)}<small>×</small></span>
          <span class="lf-score">爆文分 ${fmtBoost(item.burst_score)}</span>
          <div class="lf-actions">
            <a class="lf-act" href="${esc(item.art_url)}" target="_blank" rel="noopener noreferrer">原文</a>
            <button class="lf-act is-primary" type="button"
              data-write="${esc(item.title)}" data-type="${esc(type)}">去写这篇</button>
          </div>
        </div>
      </li>`;
    }).join('') + '</ul>';
    if (el.more) {
      el.more.hidden = state.page >= state.pages;
      el.more.textContent = `加载更多（还有 ${state.total - state.items.length} 篇）`;
    }
  }

  function renderDates() {
    if (!el.date) return;
    if (!state.dates.length) { el.date.hidden = true; return; }
    el.date.hidden = state.dates.length <= 1;
    el.date.innerHTML = state.dates.map((date) =>
      `<option value="${esc(date)}"${date === state.statDate ? ' selected' : ''}>${esc(date)}</option>`
    ).join('');
  }

  function renderNote() {
    if (!el.note) return;
    if (state.degraded) {
      el.note.hidden = false;
      el.note.className = 'lf-note is-warn';
      el.note.innerHTML = `<b>今日榜单可能延迟。</b>当前展示的是最近一次成功同步的数据（${esc(state.statDate || '—')}）。`;
    } else {
      el.note.hidden = false;
      el.note.className = 'lf-note';
      el.note.innerHTML = '榜单口径：阅读 ≥ 1 万、账号常态阅读基线 ≤ 5000、阅读提升 ≥ 5 倍。'
        + '<b>爆发倍率 = 本篇阅读 ÷ 账号基线</b>（是倍数，不是百分比）；基线取中位数与均值 35% 的较大者，窗口 90 天。';
    }
  }

  function renderTail() {
    if (!el.tail) return;
    if (!state.total) { el.tail.textContent = ''; return; }
    const from = (state.page - 1) * state.pageSize + 1;
    const to = Math.min(state.total, from + state.items.length - 1);
    el.tail.textContent = `${from}–${to} / 共 ${state.total} 篇`;
  }

  function syncUrl() {
    const params = new URLSearchParams();
    if (state.wx_type) params.set('track', state.wx_type);
    if (state.q) params.set('q', state.q);
    if (state.sort !== 'burst') params.set('sort', state.sort);
    if (state.date) params.set('date', state.date);
    const query = params.toString();
    history.replaceState(null, '', '/lowfans' + (query ? '?' + query : ''));
  }

  function readUrl() {
    const params = new URLSearchParams(location.search);
    state.wx_type = params.get('track') || '';
    state.q = params.get('q') || '';
    state.sort = params.get('sort') || 'burst';
    state.date = params.get('date') || '';
    if (el.search) el.search.value = state.q;
    if (el.sort) el.sort.value = state.sort;
  }

  async function load({ append = false } = {}) {
    if (state.loading) return;
    state.loading = true;
    if (!append) {
      state.page = 1;
      if (el.list) el.list.innerHTML = '<div class="lf-loading">正在读取榜单…</div>';
    }
    const params = new URLSearchParams({
      sort: state.sort, page: String(state.page), page_size: String(state.pageSize),
    });
    if (state.wx_type) params.set('wx_type', state.wx_type);
    if (state.q) params.set('q', state.q);
    if (state.date) params.set('date', state.date);
    try {
      const response = await fetch('/api/lowfans?' + params.toString(), { credentials: 'same-origin' });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const data = await response.json();
      state.items = append ? state.items.concat(data.items || []) : (data.items || []);
      state.total = data.total || 0;
      state.pages = data.pages || 1;
      state.categories = data.categories || [];
      state.dates = data.dates || [];
      state.statDate = data.stat_date || '';
      state.degraded = !!data.degraded;
      renderTracks();
      renderDates();
      renderList();
      renderNote();
      renderTail();
      setStatus(state.statDate ? `榜单日期 ${state.statDate}` : '暂无数据', state.degraded);
    } catch (error) {
      if (el.list) {
        el.list.innerHTML = `<div class="lf-empty"><strong>榜单读取失败</strong><p>${esc(error.message)}，请稍后重试。</p></div>`;
      }
      setStatus('读取失败', true);
    } finally {
      state.loading = false;
      state.loaded = true;
    }
  }

  /* ---------------------------------------------------------------- 事件 */
  let searchTimer = 0;
  el.search?.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const next = el.search.value.trim();
      // 搜索默认走全赛道：留着上一个赛道会让「宗教 + 裁员」这类组合直接空列表，
      // 用户会以为搜不到。
      if (next && state.wx_type) {
        state.wx_type = '';
        renderTracks();
      }
      state.q = next;
      state.page = 1;
      syncUrl();
      load();
    }, 320);
  });

  el.sort?.addEventListener('change', () => {
    state.sort = el.sort.value;
    state.page = 1;
    syncUrl();
    load();
  });

  el.date?.addEventListener('change', () => {
    state.date = el.date.value;
    state.page = 1;
    syncUrl();
    load();
  });

  el.tracks?.addEventListener('click', (event) => {
    const chip = event.target.closest('[data-track]');
    if (!chip) return;
    const next = chip.dataset.track || '';
    state.wx_type = state.wx_type === next ? '' : next;
    state.page = 1;
    syncUrl();
    load();
  });

  el.list?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-write]');
    if (!button) return;
    const topic = button.dataset.write || '';
    const type = button.dataset.type || '';
    location.href = '/workbench?topic=' + encodeURIComponent(topic)
      + (type ? '&type=' + encodeURIComponent(type) : '');
  });

  el.more?.addEventListener('click', () => {
    state.page += 1;
    load({ append: true });
  });

  el.exportBtn?.addEventListener('click', async () => {
    el.exportBtn.disabled = true;
    const original = el.exportBtn.textContent;
    el.exportBtn.textContent = '导出中…';
    try {
      const response = await fetch('/api/lowfans/export', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          wx_type: state.wx_type, q: state.q, sort: state.sort, date: state.date,
        }),
      });
      if (response.status === 401) { location.href = '/?register=1'; return; }
      if (response.status === 402) {
        alert('积分不足，导出一份 CSV 需要 2 积分。');
        return;
      }
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `lowfans-${state.statDate || 'export'}.csv`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (error) {
      alert('导出失败：' + error.message);
    } finally {
      el.exportBtn.disabled = false;
      el.exportBtn.textContent = original;
    }
  });

  window.addEventListener('popstate', () => {
    readUrl();
    load();
  });

  function ensureLoaded() {
    if (state.loaded || state.loading) return;
    readUrl();
    load();
  }

  window.LowfansView = { ensureLoaded, reload: () => load() };

  if (!root.hidden) ensureLoaded();
})();
