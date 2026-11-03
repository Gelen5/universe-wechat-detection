/* Shared viral-insights membership state and purchase UI. */
(() => {
  const state = { data: null, packages: [] };
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const modal = () => document.querySelector('#viral-insights-membership-modal');
  const fmt = (iso) => { if (!iso) return ''; const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString('zh-CN', {hour12:false}); };
  const text = (status, d) => {
    if (d?.pending_order && status !== 'member_active') return '支付待确认';
    return ({logged_out:'登录后可试用',trial_available:'开启 24 小时试用',
      trial_active:`试用中 · ${fmt(d?.trial_expires_at)} 到期`,trial_expired:'试用已结束',
      member_active:`会员有效 · ${fmt(d?.membership_expires_at)} 到期`,member_expired:'会员已过期'}[status] || '开通爆款情报会员');
  };
  async function status() {
    const r = await fetch('/api/viral-insights/membership', {credentials:'same-origin', cache:'no-store'});
    state.data = await r.json();
    state.packages = state.data.packages || [];
    document.querySelectorAll('[data-viral-insights-state]').forEach(el => {
      el.textContent = text(state.data.status, state.data);
      el.dataset.status = state.data.status || '';
    });
    // 开关关闭时完全不展示会员入口，保持原有体验。
    document.querySelectorAll('.vi-membership-button').forEach(el => { el.hidden = !state.data.enabled; });
    return state.data;
  }
  function open() {
    const node = modal(); if (!node) return;
    node.hidden = false; node.querySelector('[data-vi-modal-title]').textContent = text(state.data?.status, state.data);
    const body = node.querySelector('[data-vi-modal-body]');
    const d = state.data || {};
    body.innerHTML = d.status === 'logged_out'
      ? '<p>登录后可领取一次 24 小时试用。</p><a class="vi-primary" href="/login">去登录</a>'
      : `${d.pending_order ? `<p class="vi-pending">订单 ${esc(d.pending_order.out_trade_no)} 等待支付确认，付款完成后稍候刷新。</p>` : ''}
         <p>低粉爆文和低分爆图共用一份权益。${d.status === 'trial_available' ? '首次激活可免费查看 24 小时。' : '会员到期后立即失效；有效期内续费自动顺延。'}</p>
         ${d.status === 'trial_available' ? '<button class="vi-primary" data-vi-trial>免费试用 24 小时</button>' : ''}
         <div class="vi-packages">${state.packages.map(p => `<button data-vi-package="${esc(p.id)}"><b>${esc(p.name)}</b><span>¥${esc(p.price)} / ${p.days}天</span></button>`).join('')}</div>`;
    node.querySelectorAll('[data-vi-trial]').forEach(b => b.onclick = async () => {
      b.disabled = true;
      const r = await fetch('/api/viral-insights/trial/activate', {method:'POST', credentials:'same-origin'});
      if (!r.ok) { const p = await r.json().catch(() => ({})); alert(p.detail || '试用激活失败'); b.disabled = false; return; }
      await status(); node.hidden = true;
      window.LowfansView?.reload?.(); window.ImageBoardView?.reload?.();
    });
    node.querySelectorAll('[data-vi-package]').forEach(b => b.onclick = () => buy(b.dataset.viPackage));
  }
  async function buy(packageId) {
    const r = await fetch('/api/viral-insights/orders', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({package_id:packageId})});
    const data = await r.json();
    if (!r.ok) { alert(data.detail || '暂时无法创建订单'); return; }
    const holder = document.createElement('div'); holder.innerHTML = data.form_html; document.body.appendChild(holder); holder.querySelector('form')?.submit();
  }
  window.ViralInsightsMembership = { status, open };
  document.addEventListener('click', e => { if (e.target.closest('[data-viral-insights-open]')) open(); if (e.target.closest('[data-vi-close]')) modal().hidden = true; });
  document.addEventListener('DOMContentLoaded', () => { status().catch(() => {}); });
})();
