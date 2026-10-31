/* Extraction presentation only; media and parsing remain in server/xhs_extract.py. */
(() => {
  const root = document.querySelector('#xhs-extract');
  if (!root) return;
  const $ = selector => root.querySelector(selector);
  const form = $('#xhs-extract-form'), input = $('#xhs-extract-url'), submit = $('#xhs-extract-start');
  const empty = $('#xhs-extract-empty'), result = $('#xhs-extract-result'), errorBox = $('#xhs-extract-error');
  const progress = $('#xhs-extract-progress'), progressText = $('#xhs-extract-progress-text');
  const lightbox = $('#xhs-extract-lightbox');
  let owner, epoch = 0, controller = null, timer = null, busy = false, note = null, images = [], index = 0;
  let prefillUsed = false, opener = null;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const mediaSrc = url => `/api/xhs/media?url=${encodeURIComponent(url || '')}`;
  const getOwner = () => typeof currentAccount !== 'undefined' ? currentAccount?.id || null : null;
  const storageKey = () => owner ? `xhs-extract:draft:${owner}` : null;
  const safeLink = value => {try {const u = new URL(value); return ['http:','https:'].includes(u.protocol) ? u.href : '';} catch {return '';}};
  const numberText = value => typeof value === 'number' && value >= 0 ? value.toLocaleString('zh-CN') : '—';
  function toast(message, type) {
    if (window.PointsNotice?.toast) return window.PointsNotice.toast(message, type);
    const node = document.createElement('div'); node.className = `app-toast ${type || 'success'}`;
    node.setAttribute('role', type === 'error' ? 'alert' : 'status'); node.textContent = message;
    document.body.append(node); requestAnimationFrame(() => node.classList.add('visible'));
    setTimeout(() => {node.classList.remove('visible'); setTimeout(() => node.remove(), 220);}, 2600);
  }
  function clearError() {errorBox.hidden = true; errorBox.replaceChildren();}
  function showError(message) {
    errorBox.innerHTML = `<div><strong>这次没有拿到提取结果</strong><span>${esc(message)}</span></div><button type="button" class="xe-button" data-xe-retry>重新提取</button>`;
    errorBox.hidden = false;
  }
  async function copy(value, label) {
    try {await navigator.clipboard.writeText(value); toast(`${label}已复制`);}
    catch {
      const area = document.createElement('textarea'); area.value = value;
      area.style.cssText = 'position:fixed;opacity:0'; document.body.append(area); area.select();
      const ok = document.execCommand('copy'); area.remove();
      toast(ok ? `${label}已复制` : '复制失败，请手动选择文字', ok ? 'success' : 'error');
    }
  }
  function bundle() {
    const lines = [];
    if (note.title) lines.push(`标题：${note.title}`);
    if (note.desc) lines.push('', note.desc);
    if (note.tags?.length) lines.push('', `标签：${note.tags.map(t => `#${String(t).replace(/^#/, '')}`).join(' ')}`);
    lines.push('', `来源：${note.link}`); return lines.join('\n');
  }
  function renderStats(stats = {}) {
    return `<dl class="xe-stats">${[['liked','点赞'],['collected','收藏'],['comment','评论'],['share','分享']].map(([key,label]) => `<div><dt>${label}</dt><dd>${numberText(stats[key])}</dd></div>`).join('')}</dl>`;
  }
  function imageViewer() {
    if (!images.length) return '';
    return `<div class="xe-section-head"><h3>${note.kind === 'video' ? '视频封面' : '图片素材'}</h3><span>保留图片原始比例</span></div>
      <div class="xe-viewer"><img class="xe-main-image" src="${esc(mediaSrc(images[0].url))}" alt="第 1 张图片" role="button" aria-label="查看第 1 张大图" tabindex="0" data-xe-zoom><div class="xe-image-error" hidden><span>这张图片暂时没有加载成功</span><button type="button" class="xe-button" data-xe-reload-image>重新加载</button></div></div>
      <div class="xe-image-actions"><span data-xe-index>第 1 / ${images.length} 张</span><div><button type="button" class="xe-button" data-xe-zoom>查看大图</button><button type="button" class="xe-button" data-xe-download>下载原图 ↓</button></div></div>
      ${note.kind === 'video' ? '' : `<div class="xe-thumbs" aria-label="选择图片">${images.map((image,i) => `<button type="button" class="xe-thumb" data-xe-image="${i}" aria-label="预览第 ${i+1} 张图片" aria-pressed="${i === 0}"><img src="${esc(mediaSrc(image.url))}" alt="" loading="lazy" decoding="async"><span>${i+1}${image.live ? ' · 动图' : ''}</span></button>`).join('')}</div>`}`;
  }
  function renderMedia() {
    if (note.kind !== 'video') return imageViewer();
    if (!safeLink(note.video?.url)) return `<p class="xe-media-note">这条视频暂未返回可播放地址${images.length ? '，先展示封面。' : '。'}</p>${imageViewer()}`;
    const video = note.video;
    const details = [video.width && video.height ? `${video.width}×${video.height}` : '', video.quality || ''].filter(Boolean).join(' · ');
    const poster = safeLink(video.poster) || safeLink(images[0]?.url);
    return `<div class="xe-section-head"><h3>视频素材</h3><span>${esc(details)}</span></div>
      <video class="xe-video" controls playsinline preload="metadata" ${poster ? `poster="${esc(mediaSrc(poster))}"` : ''}><source src="${esc(mediaSrc(video.url))}" type="video/mp4">当前浏览器无法播放，请使用“打开视频”。</video>
      <div class="xe-media-note xe-video-error" hidden>视频暂时无法播放，可以重新加载或打开视频。 <button type="button" class="xe-button" data-xe-reload-video>重新加载视频</button></div>
      <div class="xe-video-actions"><a class="xe-button" href="${esc(mediaSrc(video.url))}" target="_blank" rel="noopener noreferrer">打开视频 ↗</a><button type="button" class="xe-button" data-copy="video">复制视频地址</button></div>
      ${images.length ? `<div class="xe-cover"><img src="${esc(mediaSrc(images[0].url))}" alt="视频封面"><div>视频封面</div><button type="button" class="xe-button" data-xe-zoom>查看大图</button><button type="button" class="xe-button" data-xe-download>下载封面</button></div>` : ''}`;
  }
  function render(value) {
    note = value; index = 0;
    images = (note.kind === 'video' ? (note.cover ? [note.cover] : []) : (note.images || []))
      .filter(image => image && typeof image.url === 'string' && safeLink(image.url));
    const tags = (note.tags || []).map(tag => `<span>#${esc(String(tag).replace(/^#/, ''))}</span>`).join('');
    const link = safeLink(note.link), hasMedia = images.length || note.kind === 'video';
    const kind = note.kind === 'video' ? '视频作品' : `图文${images.length ? ` · ${images.length} 张图片` : ''}`;
    const avatar = note.author?.avatar ? `<img class="xe-avatar" src="${esc(mediaSrc(note.author.avatar))}" alt="" loading="lazy">` : '<span class="xe-avatar" aria-hidden="true">作</span>';
    result.innerHTML = `<header class="xe-result-head"><div class="xe-result-info"><div class="xe-badges"><span class="xe-badge"><i aria-hidden="true"></i>提取完成</span><span class="xe-badge">${esc(kind)}</span></div><h2>${esc(note.title || '未提供标题')}</h2><div class="xe-author">${avatar}<span>${esc(note.author?.name || '未知作者')}</span>${note.published ? `<span>· ${esc(note.published)}</span>` : ''}</div></div>${renderStats(note.stats)}</header>
      <div class="xe-workspace${hasMedia ? '' : ' xe-text-only'}">${hasMedia ? `<section class="xe-media" aria-label="作品媒体">${renderMedia()}</section>` : ''}<section class="xe-document" aria-label="作品原文"><div class="xe-document-head"><h3>正文原文</h3><button type="button" class="xe-button" data-copy="body">复制正文</button></div><pre class="xe-body">${esc(note.desc || '这条作品没有正文。')}</pre>${tags ? `<div class="xe-tags">${tags}</div>` : ''}<p class="xe-source-line">保留原文分段和作品来源 · 未返回的数据展示为「—」</p><div class="xe-doc-actions"><button type="button" class="xe-button xe-primary" data-copy="bundle">复制全部文字</button>${link ? `<a class="xe-button" href="${esc(link)}" target="_blank" rel="noopener noreferrer">打开原作品 ↗</a><button type="button" class="xe-button" data-copy="link">复制链接</button>` : ''}</div></section></div>`;
    empty.hidden = true; result.hidden = false;
    const main = $('.xe-main-image');
    main?.addEventListener('error', () => {$('.xe-image-error').hidden = false;});
    main?.addEventListener('load', () => {$('.xe-image-error').hidden = true;});
    $('.xe-video')?.addEventListener('error', () => {$('.xe-video-error').hidden = false;});
  }
  function selectImage(value) {
    if (!images.length) return;
    index = (value + images.length) % images.length;
    const source = mediaSrc(images[index].url), main = $('.xe-main-image');
    if (main) {main.src = source; main.alt = `第 ${index+1} 张图片`; main.setAttribute('aria-label', `查看第 ${index+1} 张大图`); $('.xe-image-error').hidden = true;}
    root.querySelectorAll('[data-xe-image]').forEach(button => button.setAttribute('aria-pressed', String(Number(button.dataset.xeImage) === index)));
    if ($('[data-xe-index]')) $('[data-xe-index]').textContent = `第 ${index+1} / ${images.length} 张`;
    if (lightbox.open) updateLightbox();
  }
  function updateLightbox() {
    const image = lightbox.querySelector('img'); image.src = mediaSrc(images[index].url); image.alt = `${note.title || '作品图片'} · 第 ${index+1} 张`;
    $('[data-xe-lightbox-index]').textContent = `${index+1} / ${images.length}`;
    lightbox.querySelectorAll('[data-xe-prev],[data-xe-next]').forEach(button => {button.disabled = images.length < 2;});
  }
  function zoom(button) {if (!images.length) return; opener = button; updateLightbox(); lightbox.showModal();}
  async function download(button) {
    if (!images[index] || button.disabled) return;
    const sequence = epoch, image = images[index], imageNumber = index+1, currentNote = note;
    const label = button.textContent; button.disabled = true; button.textContent = '正在下载…';
    try {
      const response = await fetch(mediaSrc(image.url), {credentials:'same-origin', signal:AbortSignal.timeout(60000)});
      await window.AccountLifecycle?.checkResponse(response);
      if (sequence !== epoch) return;
      if (!response.ok) throw new Error('图片暂时无法下载，请稍后重试');
      const mime = (response.headers.get('content-type') || '').split(';')[0].trim().toLowerCase();
      const extension = {'image/jpeg':'jpg','image/png':'png','image/webp':'webp','image/gif':'gif','image/avif':'avif'}[mime];
      if (!extension) throw new Error('没有取得可下载的图片，请重新加载后再试');
      const blob = await response.blob(); if (sequence !== epoch) return;
      const url = URL.createObjectURL(blob), a = document.createElement('a');
      a.href = url; a.download = `xiaohongshu-${String(currentNote.id || 'note').replace(/[^a-zA-Z0-9_-]/g,'')}-${currentNote.kind === 'video' ? 'cover' : imageNumber}.${extension}`;
      document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast('图片已准备好下载');
    } catch (error) {if (sequence === epoch) toast(error.message || '下载未完成，请重试', 'error');}
    finally {button.disabled = false; button.textContent = label;}
  }
  root.addEventListener('click', event => {
    const target = event.target.closest('button,a,[data-xe-zoom]'); if (!target) return;
    if (target.hasAttribute('data-xe-close')) lightbox.close();
    else if (target.hasAttribute('data-xe-prev')) selectImage(index-1);
    else if (target.hasAttribute('data-xe-next')) selectImage(index+1);
    else if (target.hasAttribute('data-xe-zoom')) zoom(target);
    else if (target.hasAttribute('data-xe-download')) download(target);
    else if (target.hasAttribute('data-xe-image')) selectImage(Number(target.dataset.xeImage));
    else if (target.hasAttribute('data-xe-retry')) form.requestSubmit();
    else if (target.hasAttribute('data-xe-reload-image')) {$('.xe-image-error').hidden = true; $('.xe-main-image').src = mediaSrc(images[index].url)+`&retry=${Date.now()}`;}
    else if (target.hasAttribute('data-xe-reload-video')) {$('.xe-video-error').hidden = true; $('.xe-video source').src = mediaSrc(note.video.url)+`&retry=${Date.now()}`; $('.xe-video').load();}
    else if (target.dataset.copy && note) {
      const kind = target.dataset.copy;
      copy(kind === 'body' ? (note.desc || note.title || '') : kind === 'bundle' ? bundle() : kind === 'video' ? note.video.url : note.link,
        kind === 'body' ? '正文' : kind === 'bundle' ? '全部文字' : kind === 'video' ? '视频地址' : '作品链接');
    }
  });
  root.addEventListener('keydown', event => {
    if (event.target.matches('.xe-main-image') && ['Enter',' '].includes(event.key)) {event.preventDefault(); zoom(event.target);}
    if (lightbox.open && ['ArrowLeft','ArrowRight'].includes(event.key)) {event.preventDefault(); selectImage(index+(event.key === 'ArrowLeft' ? -1 : 1));}
  });
  lightbox.addEventListener('close', () => {if (opener?.isConnected) opener.focus({preventScroll:true});});
  lightbox.addEventListener('click', event => {
    const box = lightbox.getBoundingClientRect();
    if (event.target === lightbox && (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom)) lightbox.close();
  });
  new MutationObserver(() => {if (root.hidden && lightbox.open) lightbox.close();})
    .observe(root, {attributes:true, attributeFilter:['hidden']});
  function stop() {
    clearInterval(timer); timer = null; busy = false; progress.hidden = true;
    root.removeAttribute('aria-busy'); input.readOnly = false; submit.disabled = !owner; submit.textContent = '开始提取 →';
  }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !owner) return;
    const url = input.value.trim(); if (!url) {input.focus(); return;}
    const sequence = epoch; busy = true; clearError(); submit.disabled = true; input.readOnly = true; submit.textContent = '正在提取…';
    root.setAttribute('aria-busy','true'); progress.hidden = false;
    const elapsed = document.createElement('span'); elapsed.setAttribute('aria-hidden','true'); elapsed.textContent = '已等待 0 秒';
    progressText.replaceChildren(document.createTextNode('正在提取素材 · '), elapsed);
    $('.xe-progress-hint').textContent = note ? '保留当前结果，完成后更新' : '完成后显示文案与素材';
    const start = performance.now(); timer = setInterval(() => {elapsed.textContent = `已等待 ${Math.floor((performance.now()-start)/1000)} 秒`;}, 1000);
    controller = new AbortController();
    try {
      const response = await fetch('/api/xhs/extract', {method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',
        signal:AbortSignal.any([controller.signal, AbortSignal.timeout(90000)]), body:JSON.stringify({url})});
      await window.AccountLifecycle?.checkResponse(response);
      if (sequence !== epoch) return;
      if (!(response.headers.get('content-type') || '').includes('application/json')) throw new Error(`连接暂时异常（HTTP ${response.status}），请稍后重试`);
      const data = await response.json(); if (sequence !== epoch) return;
      window.PointsNotice?.fromResponse?.(response, data);
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '提取未完成，请稍后重试');
      if (!data.note || typeof data.note !== 'object') throw new Error('没有取得作品内容，请重新复制分享链接');
      if (lightbox.open) lightbox.close(); render(data.note);
      try {localStorage.setItem(storageKey(), JSON.stringify({url, at:Date.now()}));} catch {}
      const charged = response.headers.get('X-Points-Charged'), balance = response.headers.get('X-Points-Balance');
      toast(charged && charged !== '0' ? `提取完成，扣除 ${charged} 积分${balance ? `，余额 ${balance}` : ''}` : '提取完成');
    } catch (error) {
      if (sequence === epoch) showError(error.name === 'TimeoutError' ? '等待较久，暂未收到结果。请检查网络后再决定是否重新提取。' : (error.message || '连接中断，请稍后重试'));
    } finally {if (sequence === epoch) {controller = null; stop();}}
  });
  input.addEventListener('keydown', event => {if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {event.preventDefault(); form.requestSubmit();}});
  function syncAccount() {
    const next = getOwner(); if (next === owner) return;
    owner = next; ++epoch; controller?.abort(); controller = null; stop();
    note = null; images = []; index = 0; result.replaceChildren(); result.hidden = true; empty.hidden = false; clearError();
    if (lightbox.open) lightbox.close(); lightbox.querySelector('img').removeAttribute('src'); lightbox.querySelector('img').alt = ''; input.value = '';
    if (!owner) return;
    const prefill = !prefillUsed ? new URLSearchParams(location.search).get('url') : '';
    prefillUsed = true;
    try {input.value = prefill || JSON.parse(localStorage.getItem(storageKey()) || 'null')?.url || '';}
    catch {input.value = prefill || '';}
  }
  window.addEventListener('account-changed', syncAccount);
  syncAccount();
})();
