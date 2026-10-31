/* Shared wallet notice. 402 积分不足时直接给套餐与支付入口。 */
(() => {
  let dialog;
  let previousFocus;
  let packagesPromise = null;

  function loadPackages() {
    if (!packagesPromise) {
      packagesPromise = fetch('/api/pay/packages', { credentials: 'same-origin' })
        .then(response => (response.ok ? response.json() : Promise.reject(new Error('packages'))))
        .then(payload => (Array.isArray(payload?.packages) ? payload.packages : []))
        .catch(() => null);
    }
    return packagesPromise;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function renderPackages(list) {
    const box = dialog.querySelector('#points-notice-packages');
    box.replaceChildren();
    if (!list || !list.length) {
      const fallback = el('p', 'points-notice-empty', '套餐加载失败，请打开套餐页选购。');
      box.append(fallback);
      return;
    }
    for (const item of list) {
      const card = el('a', 'points-notice-plan');
      card.href = '/pay?package=' + encodeURIComponent(String(item.id || ''));
      card.setAttribute('data-package', String(item.id || ''));
      const head = el('span', 'points-notice-plan-head');
      head.append(el('b', null, String(item.name || '套餐')));
      head.append(el('span', 'points-notice-plan-credits', `${Number(item.credits) || 0} 积分`));
      const price = el('span', 'points-notice-plan-price', `¥${String(item.price || '')}`);
      card.append(head, price);
      box.append(card);
    }
  }

  function open(detail) {
    // Embedded one-click writing uses the parent surface, rather than a clipped dialog.
    try {
      if (parent !== window && parent.PointsNotice) { parent.PointsNotice.open(detail); return; }
    } catch { /* A standalone/cross-origin frame keeps its own accessible dialog. */ }

    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.id = 'points-notice';
      dialog.setAttribute('aria-labelledby', 'points-notice-title');
      dialog.setAttribute('aria-describedby', 'points-notice-detail');

      const close = document.createElement('button');
      close.className = 'points-notice-close';
      close.type = 'button';
      close.textContent = '×';
      close.setAttribute('aria-label', '关闭积分提示');

      const symbol = el('span', 'points-notice-symbol');
      symbol.setAttribute('aria-hidden', 'true');
      symbol.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="15" rx="4"/><path d="M3 9h18M17 14h1"/></svg>';

      const eyebrow = el('span', 'points-notice-eyebrow', '我的积分');
      const title = el('h2', null, '积分不足');
      title.id = 'points-notice-title';
      const detailNode = el('p', null, '');
      detailNode.id = 'points-notice-detail';

      const packages = el('div', 'points-notice-packages');
      packages.id = 'points-notice-packages';
      packages.append(el('p', 'points-notice-loading', '正在加载套餐…'));

      const more = el('a', 'points-notice-more', '查看完整套餐与说明 →');
      more.href = '/pricing';

      const later = document.createElement('button');
      later.className = 'points-notice-confirm';
      later.type = 'button';
      later.textContent = '稍后再说';

      dialog.append(close, symbol, eyebrow, title, detailNode, packages, more, later);
      document.body.append(dialog);

      const dismiss = () => dialog.close();
      close.addEventListener('click', dismiss);
      later.addEventListener('click', dismiss);
      dialog.addEventListener('click', event => {
        if (event.target !== dialog) return;
        const box = dialog.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right
          || event.clientY < box.top || event.clientY > box.bottom) dismiss();
      });
      dialog.addEventListener('close', () => {
        document.body.classList.remove('points-notice-open');
        if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
      });
      // 套餐卡片加载好后填充；失败时退回套餐页入口
      loadPackages().then(renderPackages);
    }

    dialog.querySelector('#points-notice-detail').textContent = detail;
    if (!dialog.open) {
      previousFocus = document.activeElement;
      dialog.showModal();
      document.body.classList.add('points-notice-open');
      loadPackages().then(renderPackages);
    }
  }

  function fromResponse(response, data) {
    if (response.status === 402 && typeof data?.detail === 'string' && data.detail.includes('积分不足')) {
      open(data.detail);
    }
  }

  window.PointsNotice = { open, fromResponse };
})();
