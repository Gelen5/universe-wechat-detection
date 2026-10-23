/* No third-party code, login, model calls or runtime GitHub requests. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const categories = ['全部', 'Agent', 'AI 编程', 'Skills', '自动化', '知识管理'];
  const coverThemes = new Set(['hermes','obsidian','deepseek','loop','codex','claude','vibe','source','harness','openclaw','skills']);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const safeUrl = value => {
    try { const u = new URL(value); return u.protocol === 'https:' && !u.username && !u.password ? u.href : ''; }
    catch { return ''; }
  };
  let books = [], snapshot = '', loadAttempt = 0, lastOpened = '';
  const shelf = $('library-shelf'), detail = $('book-detail'), grid = $('book-grid'), state = $('library-state');
  let shelfUrl = '/bookshelf';
  const storage = {
    get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; } },
  };
  const savedIds = () => { const ids = storage.get('ai-bookshelf-saved', []); return Array.isArray(ids) ? ids.filter(x => typeof x === 'string') : []; };
  function cover(book) {
    const c = book.cover || {}, theme = coverThemes.has(c.theme) ? c.theme : 'codex';
    return `<div class="book-cover cover-${theme}" aria-hidden="true"><span class="cover-series">${esc(c.series || '橙皮书 · ORANGE BOOK')}</span><strong class="cover-name">${esc(c.title || book.title).replace(/\n/g,'<br>')}</strong><span class="cover-subtitle">${esc(book.subtitle)}</span><span class="cover-art"></span><span class="cover-author">花叔 / HUASHU</span></div>`;
  }
  function stars(book) { return Number.isInteger(book.stars) ? book.stars.toLocaleString('zh-CN') : '暂未获取'; }
  function date(value) { return String(value || '').slice(0,10); }
  function filters() {
    const p = new URLSearchParams(location.search);
    return { q:p.get('q') || '', category:categories.includes(p.get('category')) ? p.get('category') : '全部' };
  }
  function showState(title, message, action, handler) {
    state.hidden = false;
    state.innerHTML = `<h2>${esc(title)}</h2><p>${esc(message)}</p>${action ? `<button type="button">${esc(action)}</button>` : ''}`;
    if (handler) state.querySelector('button').addEventListener('click',handler);
  }
  function renderShelf() {
    shelf.hidden = false; detail.hidden = true;
    document.title = 'AI 书架 · 宇宙第一工作台';
    const {q,category} = filters();
    $('book-search').value = q;
    if(q) { $('search-area').hidden = false; $('search-toggle').setAttribute('aria-expanded','true'); }
    $('book-categories').innerHTML = categories.map(c => `<button type="button" aria-pressed="${c === category}">${esc(c)}</button>`).join('');
    $('book-categories').querySelectorAll('button').forEach(b => b.addEventListener('click',() => updateFilters({category:b.textContent})));
    const found = books.filter(b => (!q.trim() || b.title.toLocaleLowerCase().includes(q.trim().toLocaleLowerCase())) && (category === '全部' || b.category === category || b.tags.includes(category)));
    $('collection-title').textContent = category === '全部' ? '全部书籍' : category;
    $('book-count').textContent = `${found.length} 本 · 按 Star 排序`;
    grid.innerHTML = found.map(b => `<article class="book-item"><a class="book-link" href="/bookshelf/${encodeURIComponent(b.id)}" data-book="${esc(b.id)}" aria-label="查看 ${esc(b.title)}，作者 ${esc(b.author)}">${cover(b)}<div class="book-meta"><h3>${esc(b.title)}</h3><p>${esc(b.author)}</p><span class="book-stars" aria-label="GitHub Star ${esc(stars(b))}">☆ ${esc(stars(b))}</span></div></a></article>`).join('');
    grid.setAttribute('aria-busy','false'); state.hidden = true;
    if(!found.length) showState('还没有找到这本书','换一个书名，或回到全部书籍看看。','查看全部',() => updateFilters({q:'',category:'全部'}));
    $('snapshot-note').textContent = `Star 快照更新于 ${date(snapshot)} · 从高到低排列`;
    shelfUrl = location.pathname + location.search;
  }
  function updateFilters(values) {
    const next = {...filters(),...values}, params = new URLSearchParams();
    if(next.q) params.set('q',next.q);
    if(next.category !== '全部') params.set('category',next.category);
    history.replaceState({},'', '/bookshelf' + (params.size ? '?' + params : ''));
    renderShelf();
  }
  function renderDetail(book) {
    shelf.hidden = true; detail.hidden = false;
    document.title = `${book.title} · AI 书架`;
    const readUrl = safeUrl(book.readUrl), github = safeUrl(book.githubUrl), licenseUrl = safeUrl(book.license?.url);
    const saved = savedIds().includes(book.id);
    detail.innerHTML = `<a href="${esc(shelfUrl)}" class="library-back" id="back-to-shelf">‹ 返回书架</a>
      <div class="detail-layout"><div class="detail-cover">${cover(book)}<p class="detail-cover-note">本站设计封面 · 非原书封面</p></div>
      <div class="detail-copy"><p class="library-eyebrow">${esc(book.category)} · 橙皮书系列</p><h1 id="detail-title" tabindex="-1">${esc(book.title)}</h1><p class="detail-subtitle">${esc(book.subtitle)}</p><a class="detail-author" href="https://github.com/alchaincyf" target="_blank" rel="noopener noreferrer">${esc(book.author)} 著 ↗</a>
      <div class="detail-stats"><span>☆ ${esc(stars(book))} GitHub Stars</span><span>更新于 ${esc(date(book.starsUpdatedAt))}</span></div>
      <div class="detail-actions"><a class="detail-read" ${readUrl ? `href="${esc(readUrl)}" target="_blank" rel="noopener noreferrer"` : 'aria-disabled="true"'}>${readUrl ? '阅读原文 ↗' : '阅读链接暂不可用'}</a><button id="save-book" class="detail-save" type="button" aria-label="${saved ? '取消收藏' : '收藏此书'}" aria-pressed="${saved}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4z"/></svg></button></div>
      <p class="detail-read-note">${readUrl ? (book.readFormat === 'PDF' ? '打开作者公开的中文版 PDF，可在 GitHub 预览或下载。' : '将在新窗口打开作者提供的公开阅读网页。') : '请通过下方 GitHub 仓库查看作者最新入口。'}${book.linkStatus === 'unverified' ? '该入口暂未完成连通性验证，可使用原仓库备用入口。' : '如果原文暂时无法访问，可从下方 GitHub 仓库继续阅读。'}${safeUrl(book.chapterReadUrl) ? `<br><a class="detail-chapter-link" href="${esc(safeUrl(book.chapterReadUrl))}" target="_blank" rel="noopener noreferrer">分章阅读 · WorkBuddy（需登录）↗</a>` : ''}</p><div id="save-feedback" class="library-local-note" role="status"></div>
      <section class="detail-about"><h2>关于这本书</h2><p>${esc(book.description)}</p></section>
      <section class="detail-source" aria-label="作者与来源"><dl><dt>作者</dt><dd>${esc(book.author)}</dd><dt>原始仓库</dt><dd>${github ? `<a href="${esc(github)}" target="_blank" rel="noopener noreferrer">${esc(github.replace('https://github.com/',''))} ↗</a>` : '仓库地址暂不可用'}</dd><dt>许可证</dt><dd>${licenseUrl ? `<a href="${esc(licenseUrl)}" target="_blank" rel="noopener noreferrer">${esc(book.license.name)} ↗</a>` : esc(book.license?.name || '未明确授权转载')}</dd><dt>阅读方式</dt><dd>官方阅读 · 本站不转载正文</dd></dl>
      <p class="detail-license">${esc(book.license?.note)}<br>${esc(book.copyright)}<br>书名与相关名称用于识别原作品，不代表作者或相关产品对本站的认可。</p></section></div></div>`;
    $('back-to-shelf').addEventListener('click', e => { if(modified(e)) return; e.preventDefault(); history.pushState({},'',shelfUrl); renderShelf(); const link = [...grid.querySelectorAll('[data-book]')].find(a => a.dataset.book === book.id); link?.focus(); });
    $('save-book').addEventListener('click', () => {
      const ids = savedIds(), wasSaved = ids.includes(book.id);
      const ok = storage.set('ai-bookshelf-saved',wasSaved ? ids.filter(id => id !== book.id) : [...ids,book.id]);
      if(ok) { $('save-book').setAttribute('aria-pressed',String(!wasSaved)); $('save-book').setAttribute('aria-label',wasSaved ? '收藏此书' : '取消收藏'); }
      $('save-feedback').textContent = ok ? (wasSaved ? '已取消收藏' : '已收藏在此浏览器') : '浏览器未允许本地保存，仍可正常阅读。';
    });
    const read = detail.querySelector('.detail-read');
    read.addEventListener('click',() => { if(readUrl) storage.set('ai-bookshelf-recent',{id:book.id,at:new Date().toISOString()}); });
  }
  function modified(e) { return e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0; }
  function route(focus = false) {
    const id = decodeURIComponent(location.pathname.replace(/^\/bookshelf\/?/,''));
    if(!id) renderShelf();
    else {
      const book = books.find(b => b.id === id);
      if(book) { lastOpened = id; renderDetail(book); }
      else { renderShelf(); grid.innerHTML = ''; showState('这本书尚未收录','回到书架，看看其他值得阅读的教程。','返回书架',() => { history.replaceState({},'','/bookshelf'); renderShelf(); }); }
    }
    if(focus) { window.scrollTo(0,0); (detail.hidden ? $('shelf-title') : $('detail-title'))?.focus(); }
  }
  grid.addEventListener('click',e => {
    const a = e.target.closest('[data-book]'); if(!a || modified(e)) return;
    e.preventDefault(); history.pushState({},'',a.getAttribute('href')); route(true);
  });
  $('shelf-title').setAttribute('tabindex','-1');
  $('search-toggle').addEventListener('click',() => { const open = $('search-area').hidden; $('search-area').hidden = !open; $('search-toggle').setAttribute('aria-expanded',String(open)); if(open) $('book-search').focus(); });
  $('book-search').addEventListener('input', e => updateFilters({q:e.target.value}));
  $('search-clear').addEventListener('click',() => { updateFilters({q:''}); $('book-search').focus(); });
  window.addEventListener('popstate',() => { route(); if(detail.hidden && lastOpened) [...grid.querySelectorAll('[data-book]')].find(a => a.dataset.book === lastOpened)?.focus(); });
  const menu = document.querySelector('.workspace-menu-toggle'), header = document.querySelector('.v3-topbar');
  function closeMenu() { header.classList.remove('nav-open'); menu.setAttribute('aria-expanded','false'); }
  menu.addEventListener('click',() => { const open = header.classList.toggle('nav-open'); menu.setAttribute('aria-expanded',String(open)); });
  document.addEventListener('keydown',e => { if(e.key === 'Escape' && header.classList.contains('nav-open')) { closeMenu(); menu.focus(); } });
  document.addEventListener('click',e => { if(!header.contains(e.target)) closeMenu(); });
  document.querySelector('#library-navigation').addEventListener('click',closeMenu);
  async function load() {
    const attempt = ++loadAttempt; grid.setAttribute('aria-busy','true'); state.hidden = true;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(),12000);
    try {
      const response = await fetch('/static/bookshelf-data.json', {signal:controller.signal});
      if(!response.ok) throw new Error('catalog unavailable');
      const catalog = await response.json();
      if(!Array.isArray(catalog.books) || !catalog.books.length || catalog.books.some(b => !b.id || !b.title || !Array.isArray(b.tags))) throw new Error('invalid catalog');
      if(attempt !== loadAttempt) return;
      books = catalog.books.sort((a,b) => (b.stars ?? -1) - (a.stars ?? -1) || a.title.localeCompare(b.title,'zh-CN'));
      snapshot = catalog.updatedAt; route();
    } catch {
      if(attempt !== loadAttempt) return;
      shelf.hidden = false; detail.hidden = true; grid.innerHTML = ''; grid.setAttribute('aria-busy','false'); $('book-count').textContent = '暂时无法载入';
      showState('书架暂时没有打开','请检查网络连接后重试。','重新载入',load);
    } finally { clearTimeout(timer); }
  }
  load();
})();
