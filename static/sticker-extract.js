(() => {
  const root = document.querySelector('#sticker-extract');
  if (!root) return;
  const $ = selector => root.querySelector(selector);
  const form = $('#sticker-form'), input = $('#sticker-url'), button = $('#sticker-start');
  const progress = $('#sticker-progress'), error = $('#sticker-error'), empty = $('#sticker-empty'), result = $('#sticker-result');
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const toast = (message, type) => { if (typeof showToast === 'function') showToast(message, type); };
  let owner = null, epoch = 0, busy = false, images = [], index = 0, selected = new Set();
  function account() {return typeof currentAccount !== 'undefined' ? currentAccount?.id || null : null;}
  function syncOwner() {
    const next = account(); if (next === owner) return;
    owner = next; epoch++; images = []; index = 0; result.replaceChildren(); result.hidden = true;
    empty.hidden = false; error.hidden = true; input.value = ''; button.disabled = !owner;
  }
  function select(n) {
    if (!images.length) return;
    index = (n + images.length) % images.length;
    const image = $('[data-sticker-main]'); image.src = images[index].url; image.alt = `第 ${index+1} 张图片`;
    $('[data-sticker-index]').textContent = `第 ${index+1} / ${images.length} 张`;
    $('[data-sticker-download]').href = images[index].url + '?download=true';
    root.querySelectorAll('[data-sticker-image]').forEach(el => el.setAttribute('aria-pressed', String(Number(el.dataset.stickerImage) === index)));
  }
  function render(data) {
    images = data.images; index = 0; selected = new Set();
    result.innerHTML = `<div class="extract-result-heading"><span class="extract-heading-icon" aria-hidden="true">✓</span><div><strong>提取结果</strong><small>图片素材已整理</small></div><span class="extract-result-kind">${images.length} 张图片</span></div>
      <div class="xe-workspace"><section class="xe-media" aria-label="图片素材"><div class="xe-section-head"><h3>图片素材</h3><span>保留图片原始比例</span></div><div class="xe-viewer"><img class="xe-main-image" data-sticker-main src="${esc(images[0].url)}" alt="第 1 张图片"></div><div class="xe-image-actions"><span data-sticker-index>第 1 / ${images.length} 张</span><div><a class="xe-button" data-sticker-download href="${esc(images[0].url)}?download=true">下载图片 ↓</a></div></div><div class="xe-thumbs" aria-label="选择图片">${images.map((item,i) => `<button type="button" class="xe-thumb" data-sticker-image="${i}" aria-label="预览第 ${i+1} 张图片" aria-pressed="${i===0}"><img src="${esc(item.url)}" alt="" loading="lazy"><span>${i+1}</span></button>`).join('')}</div><div class="sticker-select-list">${images.map((item,i) => `<label><input type="checkbox" data-sticker-select="${i}"> 选择第 ${i+1} 张</label>`).join('')}</div></section>
      <section class="xe-document" aria-label="文章信息"><header class="xe-result-head"><div class="xe-result-info"><div class="xe-badges"><span class="xe-badge"><i aria-hidden="true"></i>提取完成</span><span class="xe-badge">${images.length} 张图片</span></div><h2>${esc(data.title || '公众号文章')}</h2></div></header><p class="xe-source-line">图片按文章中的顺序排列，点击左侧缩略图可预览和下载单张图片。</p><div class="xe-doc-actions"><a class="xe-button xe-primary" href="/api/sticker-extract/${esc(data.token)}/zip">下载全部图片 ↓</a><button class="xe-button" type="button" data-sticker-remix>将选中图片用于复刻</button></div></section></div>`;
    empty.hidden = true; result.hidden = false;
  }
  root.addEventListener('click', event => {const thumb = event.target.closest('[data-sticker-image]'); if (thumb) select(Number(thumb.dataset.stickerImage));});
  root.addEventListener('change', event => {
    const box = event.target.closest('[data-sticker-select]'); if (!box) return;
    const n = Number(box.dataset.stickerSelect);
    if (box.checked && selected.size >= 8) {box.checked = false; toast('最多选择 8 张参考图', 'error'); return;}
    if (box.checked) selected.add(n); else selected.delete(n);
  });
  root.addEventListener('click', async event => {
    const target = event.target.closest('[data-sticker-remix]'); if (!target) return;
    if (!selected.size) {toast('请先选择图片', 'error'); return;}
    target.disabled = true;
    try {
      const files = [];
      for (const i of [...selected].sort((a,b) => a-b)) {
        const response = await fetch(images[i].url, {credentials:'same-origin'});
        if (!response.ok) throw new Error('图片已过期，请重新提取');
        const blob = await response.blob();
        files.push(new File([blob], `sticker-${i+1}`, {type:blob.type}));
      }
      if (!window.importStickerReferenceFiles) throw new Error('复刻功能暂不可用');
      window.importStickerReferenceFiles(files);
    } catch (err) {toast(err.message || '添加失败', 'error');}
    finally {target.disabled = false;}
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !owner) return;
    const sequence = epoch; busy = true; button.disabled = true; button.textContent = '正在提取…'; input.readOnly = true; progress.hidden = false; error.hidden = true;
    try {
      const response = await fetch('/api/sticker-extract', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({url:input.value.trim()})});
      await window.AccountLifecycle?.checkResponse(response);
      if (!(response.headers.get('content-type') || '').includes('application/json')) throw new Error('连接暂时异常，请稍后重试');
      const data = await response.json(); if (sequence !== epoch) return;
      window.PointsNotice?.fromResponse?.(response, data);
      const balance = response.headers.get('X-Points-Balance');
      if (balance !== null && typeof setWalletBalance === 'function') setWalletBalance(balance);
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '提取未完成，请稍后重试');
      if (!Array.isArray(data.images) || !data.images.length) throw new Error('没有识别到图片');
      render(data);
      const charged = response.headers.get('X-Points-Charged');
      toast(charged ? `提取完成，扣除 ${charged} 积分` : '提取完成');
    } catch (err) {if (sequence === epoch) {error.textContent = err.message || '提取失败，请稍后重试'; error.hidden = false;}}
    finally {busy = false; progress.hidden = true; input.readOnly = false; button.disabled = !account(); button.textContent = '开始提取 →';}
  });
  window.addEventListener('account-changed', syncOwner); syncOwner();
})();
