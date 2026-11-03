/* 低分爆图：读本地快照 API，不在浏览时触达上游。 */
(() => {
  const root = document.querySelector('#image-board');
  if (!root) return;
  const state = { scope: 'image', type: '', q: '', sort: 'read', date: '', loaded: false };
  const $ = (s) => root.querySelector(s);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = (v) => Number(v) >= 100000 ? '10万+' : (Number(v) || 0).toLocaleString('zh-CN');
  const render = (data) => {
    const tracks = $('#ib-tracks');
    const cats = data.categories || [];
    tracks.innerHTML = [{name:'',count:data.counts?.[state.scope] || 0}, ...cats]
      .map(x => `<button type="button" class="ib-track${(state.type || '') === x.name ? ' is-active' : ''}" data-type="${esc(x.name)}">${esc(x.name || '全部')}<n>${x.count}</n></button>`).join('');
    const items = data.items || [];
    $('#ib-tail').textContent = `${items.length} 条 · ${data.stat_date || '暂无日期'}`;
    $('#ib-grid').innerHTML = items.length ? `<div class="ib-grid">${items.map((x, i) => {
      const low = x.lowfans;
      return `<article class="ib-card"><div class="ib-cover"><img src="${esc(x.pic_url)}" alt="" loading="lazy"><span class="ib-rank">${i + 1}</span></div><div class="ib-body"><div class="ib-kicker">${esc(x.wx_type || '其他')} · ${x.image_num || 0} 图 · ${x.word_num || 0} 字</div><h2>${esc(x.title)}</h2><p>${esc(x.excerpt || '')}</p><div class="ib-meta"><b>${fmt(x.read_num)} 阅读</b><span>${fmt(x.share_num)} 分享</span>${low ? `<strong>${low.boost_ratio}× 低粉爆发</strong>` : '<span>未匹配低粉榜</span>'}</div><a href="${esc(x.art_url)}" target="_blank" rel="noopener noreferrer">查看原文 ↗</a></div></article>`;
    }).join('')}</div>` : '<div class="ib-empty"><strong>当前范围没有内容</strong><p>换一个范围或赛道试试。</p></div>';
    $('#ib-note').textContent = state.scope === 'image' ? `图为主 = 正文不超过 ${data.image_first_max_words || 100} 字、无视频且至少 1 张图；这是规则筛选，不等同于人工确认。` : state.scope === 'lowfans' ? '已匹配低粉榜：仅表示文章标识出现在当前已同步的低粉爆文快照中。' : '全部贴图：资源库 content_type=book，里面可能混有新闻和普通图文。';
    $('#ib-stamp').innerHTML = `<span>数据日期 ${esc(data.stat_date || '—')} · ${data.last_sync?.pages_ok || 0} 页 / ${data.last_sync?.cost_points || 0} 积分</span>`;
    $('#ib-scopes').querySelectorAll('[data-scope]').forEach(b => { b.querySelector('n').textContent = ` ${data.counts?.[b.dataset.scope] || 0}`; b.setAttribute('aria-selected', String(b.dataset.scope === state.scope)); });
    $('#ib-date').hidden = !(data.dates || []).length;
    $('#ib-date').innerHTML = (data.dates || []).map(d => `<option value="${esc(d)}" ${d === state.date ? 'selected' : ''}>${esc(d)}</option>`).join('');
  };
  async function load() {
    $('#ib-grid').innerHTML = '<div class="ib-empty"><strong>正在读取榜单…</strong></div>';
    const p = new URLSearchParams({ scope: state.scope, sort: state.sort });
    if (state.type) p.set('wx_type', state.type); if (state.q) p.set('q', state.q); if (state.date) p.set('date', state.date);
    try { const r = await fetch('/api/image-board?' + p, { credentials: 'same-origin' }); if (!r.ok) throw new Error(`HTTP ${r.status}`); render(await r.json()); state.loaded = true; }
    catch (e) { $('#ib-grid').innerHTML = `<div class="ib-empty"><strong>榜单读取失败</strong><p>${esc(e.message)}，请稍后重试。</p></div>`; }
  }
  $('#ib-scopes').addEventListener('click', e => { const b = e.target.closest('[data-scope]'); if (!b) return; state.scope = b.dataset.scope; state.type = ''; load(); });
  $('#ib-tracks').addEventListener('click', e => { const b = e.target.closest('[data-type]'); if (!b) return; state.type = b.dataset.type; load(); });
  $('#ib-sort').addEventListener('change', e => { state.sort = e.target.value; load(); });
  $('#ib-date').addEventListener('change', e => { state.date = e.target.value; load(); });
  let timer; $('#ib-search').addEventListener('input', e => { clearTimeout(timer); timer = setTimeout(() => { state.q = e.target.value.trim(); load(); }, 260); });
  window.ImageBoardView = { ensureLoaded: () => { if (!state.loaded) load(); } };
})();
