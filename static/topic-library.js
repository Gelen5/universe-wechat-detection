(() => {
  const $ = s => document.querySelector(s);
  let categories = [], category = '', track = '', view = 'browse', query = '', page = 1, items = [], total = 0, savedCount = 0, preview = false, mode = '', requestId = 0;
  async function api(url, options = {}) {
    const r = await fetch(url, {credentials: 'same-origin', ...options});
    if (r.status === 401) throw new Error('请先登录后使用选题灵感库');
    if (!r.ok) throw new Error('加载失败，请稍后重试');
    return r.json();
  }
  function toast(text) { const el = $('.toast'); el.textContent = text; el.style.display = 'block'; clearTimeout(toast.timer); toast.timer = setTimeout(() => el.style.display = 'none', 2200); }
  function selectedCategory() { return categories.find(x => x.name === category); }
  async function load(append = false) {
    const id = ++requestId;
    if (!append) { page = 1; items = []; $('#list').textContent = '正在加载…'; }
    const params = new URLSearchParams({category, track, q: query, saved: String(view === 'saved'), page: String(page)});
    try {
      const result = await api('/api/topic-library?' + params);
      if (id !== requestId) return;
      items = append ? items.concat(result.items) : result.items; total = result.total; savedCount = result.saved_count; preview = result.preview;
      render();
    } catch(e) { if (id === requestId) { $('#list').textContent = e.message; $('#more').style.display = 'none'; } }
  }
  function render() {
    $('#browseTab').classList.toggle('active', view === 'browse'); $('#savedTab').classList.toggle('active', view === 'saved');
    $('#savedCount').textContent = savedCount ? `(${savedCount})` : '';
    $('.filters').style.display = view === 'saved' ? 'none' : 'flex';
    $('#categoryButton span').textContent = category; $('#trackButton span').textContent = track;
    $('#heading').textContent = view === 'saved' ? '我的收藏' : query ? '搜索结果' : track;
    $('#hint').textContent = preview ? '免费预览' : `${total} 条选题`;
    const list = $('#list'); list.replaceChildren();
    if (!items.length) { let el = document.createElement('div'); el.className = 'empty'; el.textContent = view === 'saved' && !query ? '还没有收藏，点击选题上的“收藏”即可保存' : '没有找到相关选题，试试其他关键词'; list.append(el); }
    for (const x of items) {
      const card = document.createElement('article'); card.className = 'card';
      const meta = document.createElement('div'); meta.className = 'meta';
      const tag = document.createElement('span'); tag.className = 'tag'; tag.textContent = x.tag || '灵感';
      const name = document.createElement('span'); name.textContent = x.track; meta.append(tag, name);
      const title = document.createElement('h3'); title.textContent = x.title;
      const why = document.createElement('p'); why.textContent = x.reason;
      const bottom = document.createElement('div'); bottom.className = 'bottom';
      const fav = document.createElement('button'); fav.type = 'button'; fav.className = 'copy'; fav.textContent = x.saved ? '♥ 已收藏' : '♡ 收藏'; fav.setAttribute('aria-pressed', String(x.saved));
      fav.onclick = async () => { if (preview) { window.ViralInsightsMembership?.open(); return; } fav.disabled = true; try { await api('/api/topic-library/favorites/' + x.id, {method: x.saved ? 'DELETE' : 'PUT'}); toast(x.saved ? '已取消收藏' : '已加入收藏'); await load(); } catch (e) { toast(e.message); } finally { fav.disabled = false; } };
      const copy = document.createElement('button'); copy.className = 'copy'; copy.textContent = '复制选题'; copy.onclick = async () => { if (preview) { window.ViralInsightsMembership?.open(); return; } try { await navigator.clipboard.writeText(x.title); toast('选题已复制'); } catch { toast('复制失败，请长按标题复制'); } };
      bottom.append(fav, copy); card.append(meta, title, why, bottom); list.append(card);
    }
    if (preview) { const lock = document.createElement('div'); lock.className = 'vi-lock'; const title = document.createElement('strong'); title.textContent = '开启 5 小时免费试用，查看完整选题'; const desc = document.createElement('p'); desc.textContent = '选题灵感库、低粉爆文和低粉爆图共用权益，主动开启后才开始计时。'; const button = document.createElement('button'); button.className = 'vi-primary'; button.textContent = '查看试用与会员权益'; button.type = 'button'; button.onclick = () => window.ViralInsightsMembership?.open(); lock.append(title, desc, button); list.append(lock); }
    $('#more').style.display = !preview && items.length < total ? 'block' : 'none';
  }
  function closeSheet() { $('#overlay').classList.remove('open'); document.body.style.overflow = ''; }
  function options() {
    let q = $('#sheetsearch').value.trim(), names = mode === 'category' ? categories.map(x => x.name) : selectedCategory().tracks.map(x => x.name), list = $('#options'); list.replaceChildren();
    for (const name of names.filter(x => x.includes(q))) {
      const b = document.createElement('button'); b.className = 'option' + ((mode === 'category' ? category : track) === name ? ' selected' : '');
      const left = document.createElement('span'), right = document.createElement('span'); left.textContent = name; right.className = 'right'; right.textContent = (mode === 'category' ? category : track) === name ? '✓' : '›'; b.append(left, right);
      b.onclick = () => { if (mode === 'category') { category = name; track = selectedCategory().tracks[0].name; } else track = name; query = ''; $('#search').value = ''; $('.clear').style.display = 'none'; closeSheet(); load(); }; list.append(b);
    }
    if (!list.children.length) { const el = document.createElement('div'); el.className = 'empty'; el.textContent = '没有找到匹配项'; list.append(el); }
  }
  function openSheet(m) { if (preview) { window.ViralInsightsMembership?.open('filter'); return; } mode = m; $('#sheettitle').textContent = m === 'category' ? '选择分类' : '选择赛道'; $('#sheetsearch').value = ''; $('#sheetsearch').placeholder = m === 'category' ? '搜索分类' : '搜索赛道'; $('#overlay').classList.add('open'); document.body.style.overflow = 'hidden'; options(); }
  $('#categoryButton').onclick = () => openSheet('category'); $('#trackButton').onclick = () => openSheet('track'); $('.close').onclick = closeSheet;
  $('#overlay').onclick = e => { if (e.target.id === 'overlay') closeSheet(); }; document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSheet(); }); $('#sheetsearch').oninput = options;
  $('#browseTab').onclick = () => { view = 'browse'; load(); }; $('#savedTab').onclick = () => { if (preview) { window.ViralInsightsMembership?.open(); return; } view = 'saved'; load(); };
  let debounce; $('#search').addEventListener('focus', () => { if (preview) { $('#search').blur(); window.ViralInsightsMembership?.open('filter'); } }); $('#search').oninput = e => { query = e.target.value.trim(); $('.clear').style.display = query ? 'block' : 'none'; clearTimeout(debounce); debounce = setTimeout(load, 250); };
  $('.clear').onclick = e => { e.preventDefault(); $('#search').value = ''; query = ''; $('.clear').style.display = 'none'; clearTimeout(debounce); load(); };
  $('#more').onclick = () => { page++; load(true); };
  window.TopicLibraryView = { reload: () => load() };
  (async () => { try { const data = await api('/api/topic-library/categories'); categories = data.categories; category = categories[0].name; track = categories[0].tracks[0].name; await load(); } catch(e) { $('#list').textContent = e.message; } })();
})();
