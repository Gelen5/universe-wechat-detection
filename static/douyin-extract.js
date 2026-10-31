/*
 * douyin-extract.js — 抖音内容提取的前端交互（/douyin-extract）
 *
 * 边界说明：
 *   - 这个文件只负责「发请求 + 把结果画出来」，签名和解析都在服务端
 *     （server/douyin_extract.py），浏览器里不出现任何签名逻辑。
 *   - 视频不直接用上游地址：抖音的播放地址带 x-expires，几十分钟就失效。
 *     这里一律指到 /api/douyin/video?id=<aweme_id>，由服务端每次现取现转。
 *   - 图片走 /api/douyin/media 同源代理 + 服务端磁盘缓存，因为图床地址同样
 *     带签名有效期，直连会裂图。
 *   - 不复用 app.js 的私有函数：app.js 是顶层 IIFE，里面的 showToast 拿不到。
 *     这里保持零耦合。积分提示复用全站的 window.PointsNotice。
 */
(() => {
  const root = document.querySelector('#douyin-extract');
  if (!root) return;

  const form = root.querySelector('#douyin-extract-form');
  const input = root.querySelector('#douyin-extract-url');
  const submit = root.querySelector('#douyin-extract-start');
  const empty = root.querySelector('#douyin-extract-empty');
  const result = root.querySelector('#douyin-extract-result');
  const errorBox = root.querySelector('#douyin-extract-error');
  const DRAFT_KEY = 'douyin-extract:draft';

  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]
  ));

  const mediaSrc = url => `/api/douyin/media?url=${encodeURIComponent(url || '')}`;
  // 视频用 aweme_id 而不是上游地址：地址会过期，id 不会。
  const videoSrc = id => `/api/douyin/video?id=${encodeURIComponent(id || '')}`;

  const numberText = value => (
    typeof value === 'number' && value >= 0 ? value.toLocaleString('en-US') : '—'
  );

  const clockText = ms => {
    if (!ms) return '';
    const total = Math.round(ms / 1000);
    const minutes = Math.floor(total / 60);
    const seconds = total % 60;
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  };

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
      const area = document.createElement('textarea');
      area.value = text;
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand('copy');
      area.remove();
      toast(ok ? `${label}已复制` : '复制失败，请手动选择', ok ? 'success' : 'error');
    }
  }

  /** 拼一份能直接贴进工作台的纯文本包：正文 + 标签 + 作者 + 来源。 */
  function buildBundle(note) {
    const lines = [];
    if (note.desc) lines.push(note.desc);
    if (note.tags?.length) {
      // 抖音的正文里通常已经带 #话题，避免重复贴两遍。
      const missing = note.tags.filter(tag => !(note.desc || '').includes(tag));
      if (missing.length) lines.push('', `标签：${missing.join(' ')}`);
    }
    if (note.author?.name) lines.push('', `作者：${note.author.name}`);
    if (note.published) lines.push(`发布：${note.published}`);
    lines.push('', `来源：${note.link}`);
    return lines.filter(line => line !== undefined).join('\n');
  }

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

  function renderStats(note) {
    const stats = note.stats || {};
    // 抖音的「播放」只有作者本人看得到，访客视角一般是 -1，这里不硬凑。
    const cells = [
      ['点赞', stats.liked],
      ['评论', stats.comment],
      ['收藏', stats.collected],
      ['分享', stats.share],
    ];
    if (typeof stats.play === 'number' && stats.play > 0) cells.push(['播放', stats.play]);
    const items = cells
      .map(([label, value]) => `<div><dt>${label}</dt><dd>${numberText(value)}</dd></div>`)
      .join('');
    return `<dl class="dy-stats">${items}</dl>`;
  }

  function renderVideo(note) {
    const video = note.video;
    if (!video?.url) return '';
    const meta = [
      video.width && video.height ? `${video.width}×${video.height}` : '',
      video.quality || '',
      clockText(video.duration),
    ].filter(Boolean).join(' · ');
    const src = videoSrc(note.id);
    return `<section class="dy-card">
      <div class="dy-media-head">
        <h3>视频</h3>
        <span>${esc(meta)}</span>
      </div>
      <video class="dy-video" controls preload="metadata" playsinline
             ${video.poster ? `poster="${esc(mediaSrc(video.poster))}"` : ''}>
        <source src="${esc(src)}" type="video/mp4">
        当前浏览器不支持视频播放，请使用下方「在新标签打开视频」。
      </video>
      <div class="dy-actions">
        <a class="dy-btn" href="${esc(src)}" target="_blank" rel="noopener">在新标签打开视频</a>
        <button type="button" class="dy-btn" data-copy-video>复制视频地址</button>
        <span class="dy-hint-inline">视频由本站转存，链接长期有效</span>
      </div>
    </section>`;
  }

  function renderGallery(note) {
    const images = note.images || [];
    if (!images.length) return '';
    const shots = images.map((image, index) => `
      <a class="dy-shot" href="${esc(mediaSrc(image.url))}" target="_blank" rel="noopener"
         title="打开原图 ${index + 1}">
        <img src="${esc(mediaSrc(image.url))}" alt="第 ${index + 1} 张配图" loading="lazy" decoding="async">
        <span class="dy-shot-index">${index + 1}</span>
      </a>`).join('');
    return `<section class="dy-card">
      <div class="dy-media-head">
        <h3>配图 · ${images.length} 张</h3>
        <span>点开是大图，右键可直接另存</span>
      </div>
      <div class="dy-gallery">${shots}</div>
    </section>`;
  }

  function render(note) {
    const tags = (note.tags || []).map(tag => `<span class="dy-chip">${esc(tag)}</span>`).join('');
    const avatar = note.author?.avatar
      ? `<img src="${esc(mediaSrc(note.author.avatar))}" alt="" loading="lazy">` : '';
    const authorName = note.author?.name || '未知作者';
    const kindLabel = note.kind === 'video' ? '视频作品' : '图文作品';
    const countChip = note.kind === 'image' && note.imageCount
      ? `<span class="dy-chip muted">${note.imageCount} 张图</span>` : '';
    const durationChip = note.kind === 'video' && note.duration
      ? `<span class="dy-chip muted">${clockText(note.duration)}</span>` : '';

    result.innerHTML = `
      <section class="dy-card">
        <div class="dy-card-head">
          <span class="dy-chip">${kindLabel}</span>
          ${note.published ? `<span class="dy-chip muted">${esc(note.published)}</span>` : ''}
          ${countChip}
          ${durationChip}
        </div>
        ${note.title ? `<h3>${esc(note.title)}</h3>` : ''}
        <div class="dy-author">${avatar}<span>${esc(authorName)}</span></div>
        ${renderStats(note)}
        ${note.desc ? `<pre class="dy-body">${esc(note.desc)}</pre>` : '<p>这条作品没有文案。</p>'}
        ${tags ? `<div class="dy-tags">${tags}</div>` : ''}
        <div class="dy-actions">
          <button type="button" class="dy-btn primary" data-copy="body">复制文案</button>
          <button type="button" class="dy-btn" data-copy="bundle">复制全部文字</button>
          <button type="button" class="dy-btn" data-copy="link">复制作品链接</button>
          <a class="dy-btn" href="${esc(note.link)}" target="_blank" rel="noopener noreferrer">打开原作品 ↗</a>
        </div>
      </section>
      ${renderVideo(note)}
      ${renderGallery(note)}`;

    result.hidden = false;
    empty.hidden = true;
    bindActions(note);

    result.querySelector('[data-copy-video]')?.addEventListener(
      'click', () => copy(videoSrc(note.id), '视频地址')
    );
    const video = result.querySelector('.dy-video');
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
    const response = await fetch('/api/douyin/extract', {
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

  input.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  const prefill = new URLSearchParams(location.search).get('url');
  if (prefill && !input.value) input.value = prefill;
})();
