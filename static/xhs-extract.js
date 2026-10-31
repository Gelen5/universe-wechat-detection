/*
 * xhs-extract.js — 小红书内容提取的前端交互（/xhs-extract）
 *
 * 边界说明：
 *   - 这个文件只负责「发请求 + 把结果画出来」，抓取和解析都在服务端
 *     （server/xhs_extract.py），避免把平台的解析细节复制到浏览器里。
 *   - 不复用 app.js 的私有函数：app.js 是一个顶层 IIFE，里面的
 *     showToast / readApiResponse 都在闭包里拿不到。这里保持零耦合，
 *     将来 app.js 拆分也不会连带这个页面。
 *   - 积分提示复用全站的 window.PointsNotice（如果存在）。
 */
(() => {
  const root = document.querySelector('#xhs-extract');
  if (!root) return;

  const form = root.querySelector('#xhs-extract-form');
  const input = root.querySelector('#xhs-extract-url');
  const submit = root.querySelector('#xhs-extract-start');
  const empty = root.querySelector('#xhs-extract-empty');
  const result = root.querySelector('#xhs-extract-result');
  const errorBox = root.querySelector('#xhs-extract-error');
  const DRAFT_KEY = 'xhs-extract:draft';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));

  // 媒体一律走同源代理：小红书图床带防盗链和跨域限制，直连会裂图。
  const mediaSrc = url => `/api/xhs/media?url=${encodeURIComponent(url || '')}`;

  const numberText = value => (
    typeof value === 'number' && value >= 0 ? value.toLocaleString('en-US') : '—'
  );

  function toast(message, type) {
    if (window.PointsNotice?.toast) { window.PointsNotice.toast(message, type); return; }
    const node = document.createElement('div');
    node.className = `app-toast ${type || 'success'}`;
    node.setAttribute('role', type === 'error' ? 'alert' : 'status');
    node.textContent = message;
    document.body.appendChild(node);
    requestAnimationFrame(() => node.classList.add('visible'));
    setTimeout(() => { node.classList.remove('visible'); setTimeout(() => node.remove(), 220); }, 2600);
  }

  function showError(html) {
    errorBox.innerHTML = `<span aria-hidden="true">⚠️</span><div>${html}</div>`;
    errorBox.hidden = false;
  }

  function clearError() {
    errorBox.hidden = true;
    errorBox.innerHTML = '';
  }

  async function copy(text, label) {
    try {
      await navigator.clipboard.writeText(text);
      toast(`${label}已复制`);
    } catch {
      // 剪贴板在非 HTTPS 或未授权时不可用，退回选中方案。
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand('copy');
      area.remove();
      toast(ok ? `${label}已复制` : `复制失败，请手动选择`, ok ? 'success' : 'error');
    }
  }

  /** 结果卡片里的所有复制按钮共用一套委托逻辑。 */
  function bindActions(note) {
    result.querySelectorAll('[data-copy]').forEach(button => {
      button.addEventListener('click', () => {
        const kind = button.dataset.copy;
        if (kind === 'body') copy(note.desc || note.title || '', '正文');
        else if (kind === 'link') copy(note.link, '作品链接');
        else if (kind === 'bundle') copy(buildBundle(note), '全部文字');
      });
    });
  }

  /** 拼一份能直接贴进工作台的纯文本包：标题 + 正文 + 标签。 */
  function buildBundle(note) {
    const lines = [];
    if (note.title) lines.push(`标题：${note.title}`);
    if (note.desc) lines.push('', note.desc);
    if (note.tags?.length) lines.push('', `标签：${note.tags.map(t => `#${t}`).join(' ')}`);
    lines.push('', `来源：${note.link}`);
    return lines.join('\n');
  }

  function renderStats(note) {
    const stats = note.stats || {};
    return `<dl class="xhs-stats">
      <div><dt>点赞</dt><dd>${numberText(stats.liked)}</dd></div>
      <div><dt>收藏</dt><dd>${numberText(stats.collected)}</dd></div>
      <div><dt>评论</dt><dd>${numberText(stats.comment)}</dd></div>
      <div><dt>分享</dt><dd>${numberText(stats.share)}</dd></div>
    </dl>`;
  }

  function renderGallery(note) {
    // 视频作品单独的封面字段，图片作品才走配图墙。
    const images = note.kind === 'video'
      ? (note.cover ? [note.cover] : [])
      : (note.images || []);
    if (!images.length) return '';
    const isCover = note.kind === 'video';
    const shots = images.map((image, index) => `
      <a class="xhs-shot" href="${esc(mediaSrc(image.url))}" target="_blank" rel="noopener"
         title="打开原图 ${index + 1}">
        <img src="${esc(mediaSrc(image.url))}" alt="${isCover ? '视频封面' : `第 ${index + 1} 张配图`}" loading="lazy" decoding="async">
        <span class="xhs-shot-index">${index + 1}</span>
        ${image.live ? '<span class="xhs-shot-live">动图</span>' : ''}
      </a>`).join('');
    return `<section class="xhs-card">
      <div class="xhs-media-head">
        <h3>${isCover ? '封面' : `配图 · ${images.length} 张`}</h3>
        <span>点开是大图，右键可直接另存</span>
      </div>
      <div class="xhs-gallery">${shots}</div>
    </section>`;
  }

  function renderVideo(note) {
    const video = note.video;
    if (!video?.url) return '';
    const meta = [video.width && video.height ? `${video.width}×${video.height}` : '',
                  video.quality || '', video.duration ? `${video.duration}s` : '']
      .filter(Boolean).join(' · ');
    return `<section class="xhs-card">
      <div class="xhs-media-head">
        <h3>视频</h3>
        <span>${esc(meta)}</span>
      </div>
      <video class="xhs-video" controls preload="metadata"
             ${video.poster ? `poster="${esc(mediaSrc(video.poster))}"` : ''}>
        <source src="${esc(mediaSrc(video.url))}" type="video/mp4">
        当前浏览器不支持视频播放，请使用下方「复制视频地址」。
      </video>
      <div class="xhs-actions">
        <button type="button" class="xhs-btn" data-open-video>在新标签打开视频</button>
        <button type="button" class="xhs-btn" data-copy-video>复制视频地址</button>
      </div>
    </section>`;
  }

  function render(note) {
    const tags = (note.tags || []).map(tag => `<span class="xhs-chip">#${esc(tag)}</span>`).join('');
    const avatar = note.author?.avatar
      ? `<img src="${esc(mediaSrc(note.author.avatar))}" alt="" loading="lazy">` : '';
    const authorName = note.author?.name || '未知作者';
    const kindLabel = note.kind === 'video' ? '视频作品' : '图文作品';
    // 视频作品的 imageCount 是封面帧，不能冒充「N 张图」。
    const countChip = note.kind === 'video'
      ? ''
      : (note.imageCount ? `<span class="xhs-chip muted">${note.imageCount} 张图</span>` : '');

    result.innerHTML = `
      <section class="xhs-card">
        <div class="xhs-card-head">
          <span class="xhs-chip">${kindLabel}</span>
          ${note.published ? `<span class="xhs-chip muted">${esc(note.published)}</span>` : ''}
          ${countChip}
        </div>
        ${note.title ? `<h3>${esc(note.title)}</h3>` : ''}
        <div class="xhs-author">${avatar}<span>${esc(authorName)}</span></div>
        ${renderStats(note)}
        ${note.desc ? `<pre class="xhs-body">${esc(note.desc)}</pre>` : '<p>这条作品没有正文。</p>'}
        ${tags ? `<div class="xhs-tags">${tags}</div>` : ''}
        <div class="xhs-actions">
          <button type="button" class="xhs-btn primary" data-copy="body">复制正文</button>
          <button type="button" class="xhs-btn" data-copy="bundle">复制全部文字</button>
          <button type="button" class="xhs-btn" data-copy="link">复制作品链接</button>
          <a class="xhs-btn" href="${esc(note.link)}" target="_blank" rel="noopener noreferrer">打开原作品 ↗</a>
        </div>
      </section>
      ${renderVideo(note)}
      ${renderGallery(note)}`;

    result.hidden = false;
    empty.hidden = true;
    bindActions(note);

    const video = result.querySelector('.xhs-video');
    result.querySelector('[data-open-video]')?.addEventListener('click', () => {
      window.open(mediaSrc(note.video.url), '_blank', 'noopener');
    });
    result.querySelector('[data-copy-video]')?.addEventListener('click', () => copy(note.video.url, '视频地址'));
    if (video) video.load?.();
    result.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function reset() {
    result.hidden = true;
    result.innerHTML = '';
    empty.hidden = false;
    clearError();
  }

  async function extract(url) {
    const response = await fetch('/api/xhs/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ url }),
    });
    const type = response.headers.get('content-type') || '';
    if (!type.includes('application/json')) {
      throw new Error(response.status === 401
        ? '登录已失效，请刷新页面重新登录'
        : `服务器响应异常（HTTP ${response.status}），请稍后重试`);
    }
    const data = await response.json();
    window.PointsNotice?.fromResponse?.(response, data);
    if (!response.ok) throw new Error(data.detail || '提取失败');
    // 现在按次扣费：告诉用户这一次花了多少、还剩多少，比默默扣掉更可信。
    const charged = response.headers.get('X-Points-Charged');
    if (charged && charged !== '0') {
      const balance = response.headers.get('X-Points-Balance');
      toast(`本次提取扣除 ${charged} 积分${balance ? `，余额 ${balance}` : ''}`);
    }
    return data.note;
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    const url = input.value.trim();
    if (!url) { input.focus(); return; }
    clearError();
    const label = submit.textContent;
    submit.disabled = true;
    submit.textContent = '正在提取…';
    try {
      const note = await extract(url);
      render(note);
      try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ url, id: note.id, at: Date.now() })); } catch {}
    } catch (error) {
      reset();
      showError(`<b>没提取成功：</b>${esc(error.message)}`);
      toast(error.message, 'error');
    } finally {
      submit.disabled = false;
      submit.textContent = label;
    }
  });

  // 记住上一次的链接：素材整理常有「同一条作品看两次」的场景。
  try {
    const draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
    if (draft?.url && !input.value) input.value = draft.url;
  } catch {}

  // Ctrl/Cmd + Enter 直接提交，省一次鼠标移动。
  input.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  // 支持直接带 ?url= 进来（比如从别处跳转过来预填）。
  const prefill = new URLSearchParams(location.search).get('url');
  if (prefill && !input.value) input.value = prefill;
})();
