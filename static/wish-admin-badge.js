/* 管理员提醒：心愿广场待审核红点 + 首页提醒条。
   只对管理员生效——接口 403 时自动隐藏，普通用户看不到任何东西。 */
(() => {
  const POLL_MS = 60000;
  let pending = 0;
  let timer = null;

  const style = document.createElement('style');
  style.textContent = `
    .wish-admin-count{margin-left:auto;min-width:20px;height:20px;padding:0 6px;border-radius:999px;
      background:#d64545;color:#fff;font-size:12px;line-height:20px;text-align:center;font-weight:600}
    .wish-admin-banner{display:flex;align-items:center;justify-content:space-between;gap:12px;
      margin:0 0 18px;padding:13px 18px;border-radius:14px;text-decoration:none;
      background:#fff4e8;border:1px solid #f0c9a8;color:#8a4b18}
    .wish-admin-banner strong{font-size:15px}
    .wish-admin-banner span{font-size:13px;color:#a4672f}
    .wish-admin-banner:hover{background:#ffefdd}
  `;
  document.head.append(style);

  function paintBadge() {
    const link = document.querySelector('#workspace-navigation a[href="/wish-square"]');
    if (!link) return;
    let node = link.querySelector('.wish-admin-count');
    if (!pending) { node?.remove(); return; }
    if (!node) {
      node = document.createElement('span');
      node.className = 'wish-admin-count';
      link.append(node);
    }
    node.textContent = String(pending);
  }

  function paintBanner() {
    const existing = document.querySelector('#wish-admin-banner');
    if (!pending) { existing?.remove(); return; }
    const home = document.querySelector('#home');
    if (!home) return;
    let node = existing;
    if (!node || !node.isConnected) {
      node = document.createElement('a');
      node.id = 'wish-admin-banner';
      node.className = 'wish-admin-banner';
      home.prepend(node);
    }
    node.href = '/wish-review';
    node.innerHTML = `<strong>有 ${pending} 条心愿等待审核</strong><span>点这里处理 →</span>`;
  }

  function paint() { paintBadge(); paintBanner(); }

  async function poll() {
    try {
      const response = await fetch('/api/wishes/admin/pending-count', { headers: { Accept: 'application/json' } });
      if (response.status === 401 || response.status === 403) {
        pending = 0; paint(); stop(); return;
      }
      if (!response.ok) return;
      const data = await response.json();
      pending = Number(data.pending) || 0;
      paint();
    } catch { /* 网络抖动就等下一轮 */ }
  }

  function stop() { if (timer) { clearInterval(timer); timer = null; } }

  function start() {
    stop();
    poll();
    timer = setInterval(poll, POLL_MS);
  }

  // 侧栏会被 notion-workspace 重建，重建后立刻把红点补回去。
  const nav = document.querySelector('#workspace-navigation');
  if (nav) new MutationObserver(() => paintBadge()).observe(nav, { childList: true, subtree: true });

  window.addEventListener('account-changed', start);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
