/* Shared wallet notice. Payment and provider errors retain their existing paths. */
(() => {
  let dialog;
  let previousFocus;
  function open(detail) {
    // Embedded one-click writing uses the parent surface, rather than a clipped dialog.
    try {
      if (parent !== window && parent.PointsNotice) { parent.PointsNotice.open(detail); return; }
    } catch { /* A standalone/cross-origin frame keeps its own accessible dialog. */ }
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'points-notice';
      dialog.setAttribute('aria-labelledby', 'points-notice-title');
      dialog.setAttribute('aria-describedby', 'points-notice-detail points-notice-contact');
      dialog.innerHTML = `<button class="points-notice-close" type="button" aria-label="关闭积分提示">×</button>
        <span class="points-notice-symbol" aria-hidden="true"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="15" rx="4"/><path d="M3 9h18M17 14h1"/></svg></span>
        <span class="points-notice-eyebrow">我的积分</span>
        <h2 id="points-notice-title">积分不足</h2>
        <p id="points-notice-detail"></p>
        <div class="points-notice-contact"><p id="points-notice-contact">购买积分请联系🌍Gelen5</p>
        <button class="points-notice-copy" type="button">复制联系方式</button><span class="points-notice-feedback" role="status" aria-live="polite"></span></div>
        <button class="points-notice-confirm" type="button" autofocus>我知道了</button>`;
      document.body.append(dialog);
      const close = () => dialog.close();
      dialog.querySelector('.points-notice-close').addEventListener('click', close);
      dialog.querySelector('.points-notice-confirm').addEventListener('click', close);
      dialog.addEventListener('click', event => { if (event.target === dialog) {
        const box = dialog.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) close();
      }});
      dialog.addEventListener('close', () => {
        document.body.classList.remove('points-notice-open');
        if (previousFocus?.isConnected) previousFocus.focus({preventScroll:true});
      });
      dialog.querySelector('.points-notice-copy').addEventListener('click', async () => {
        const feedback = dialog.querySelector('.points-notice-feedback');
        try { await navigator.clipboard.writeText('Gelen5'); feedback.textContent = '已复制 Gelen5'; }
        catch { feedback.textContent = '请手动复制 Gelen5'; }
      });
    }
    dialog.querySelector('#points-notice-detail').textContent = detail;
    dialog.querySelector('.points-notice-feedback').textContent = '';
    if (!dialog.open) {
      previousFocus = document.activeElement;
      dialog.showModal();
      document.body.classList.add('points-notice-open');
    }
  }
  function fromResponse(response, data) {
    if (response.status === 402 && typeof data?.detail === 'string' && data.detail.includes('积分不足')) open(data.detail);
  }
  window.PointsNotice = {open, fromResponse};
})();
