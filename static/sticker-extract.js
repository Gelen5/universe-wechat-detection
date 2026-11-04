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
    const guestInput = !owner && next ? input.value : '';
    owner = next; epoch++; images = []; index = 0; result.replaceChildren(); result.hidden = true;
    empty.hidden = false; error.hidden = true; input.value = guestInput; button.disabled = false;
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
    result.innerHTML = `<div class="sticker-result-head"><div><span class="sticker-kicker">提取完成 · ${images.length} 张图片</span><h2>${esc(data.title || '公众号文章')}</h2></div><a class="xe-button xe-primary" href="/api/sticker-extract/${esc(data.token)}/zip">下载全部图片 ↓</a></div>
      <div class="sticker-workspace"><section class="sticker-preview" aria-label="图片预览"><div class="sticker-section-head"><h3>图片预览</h3><span data-sticker-index>第 1 / ${images.length} 张</span></div><div class="xe-viewer"><img class="xe-main-image" data-sticker-main src="${esc(images[0].url)}" alt="第 1 张图片"></div><div class="sticker-preview-actions"><span>原始比例</span><a class="xe-button" data-sticker-download href="${esc(images[0].url)}?download=true">下载当前图片 ↓</a></div></section>
      <section class="sticker-gallery" aria-label="图片列表"><div class="sticker-section-head"><div><h3>图片列表</h3><p>点击图片预览，勾选后可用于复刻</p></div><span data-sticker-count>已选 0 / 8</span></div><div class="sticker-grid">${images.map((item,i) => `<div class="sticker-card"><button type="button" class="sticker-thumb" data-sticker-image="${i}" aria-label="预览第 ${i+1} 张图片" aria-pressed="${i===0}"><img src="${esc(item.url)}" alt="" loading="lazy"><span>${String(i+1).padStart(2,'0')}</span></button><label class="sticker-pick"><input type="checkbox" data-sticker-select="${i}"><span>选择</span></label></div>`).join('')}</div><div class="sticker-gallery-actions"><span>最多选择 8 张参考图</span><button class="xe-button xe-primary" type="button" data-sticker-remix>将选中图片用于复刻 →</button></div></section></div>`;
    empty.hidden = true; result.hidden = false;
  }
  root.addEventListener('click', event => {const thumb = event.target.closest('[data-sticker-image]'); if (thumb) select(Number(thumb.dataset.stickerImage));});
  root.addEventListener('change', event => {
    const box = event.target.closest('[data-sticker-select]'); if (!box) return;
    const n = Number(box.dataset.stickerSelect);
    if (box.checked && selected.size >= 8) {box.checked = false; toast('最多选择 8 张参考图', 'error'); return;}
    if (box.checked) selected.add(n); else selected.delete(n);
    $('[data-sticker-count]').textContent = `已选 ${selected.size} / 8`;
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
    event.preventDefault(); if (busy) return;
    if (!owner) { showAuth(true); return; }
    const sequence = epoch; busy = true; button.disabled = true; button.textContent = '正在提取…'; input.readOnly = true; progress.hidden = false; error.hidden = true;
    try {
      const response = await fetch('/api/sticker-extract', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({url:input.value.trim()})});
      await window.AccountLifecycle?.checkResponse(response);
      if (!(response.headers.get('content-type') || '').includes('application/json')) throw new Error('连接暂时异常，请稍后重试');
      const data = await response.json(); if (sequence !== epoch) return;
      if (response.status === 402) { window.PointsNotice?.open?.('积分不足，请先充值'); data.detail = '积分不足，请先充值'; }
      const balance = response.headers.get('X-Points-Balance');
      if (balance !== null && typeof setWalletBalance === 'function') setWalletBalance(balance);
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '提取未完成，请稍后重试');
      if (!Array.isArray(data.images) || !data.images.length) throw new Error('没有识别到图片');
      render(data);
      toast('提取完成');
    } catch (err) {if (sequence === epoch) {error.textContent = err.message || '提取失败，请稍后重试'; error.hidden = false;}}
    finally {busy = false; progress.hidden = true; input.readOnly = false; button.disabled = false; button.textContent = '开始提取 →';}
  });
  window.addEventListener('account-changed', syncOwner); syncOwner();
})();
