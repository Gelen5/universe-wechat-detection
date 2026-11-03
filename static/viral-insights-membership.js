/* Shared viral-insights membership state and purchase UI. */
(() => {
  const state = { data: null, packages: [] };
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const modal = () => document.querySelector('#viral-insights-membership-modal');
  const fmt = (iso) => { if (!iso) return ''; const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString('zh-CN', {hour12:false}); };
  const text = (status, d) => {
    if (d?.pending_order && status === 'trial_active') return `试用中 · ${fmt(d?.trial_expires_at)} 到期（订单待支付）`;
    if (d?.pending_order && !['member_active', 'owner_permanent'].includes(status)) return '订单待支付 · 尚未开通会员';
    return ({logged_out:'登录后可试用',trial_available:'开启 5 小时试用',
      trial_active:`试用中 · ${fmt(d?.trial_expires_at)} 到期`,trial_expired:'试用已结束',
      member_active:`会员有效 · ${fmt(d?.membership_expires_at)} 到期`,owner_permanent:'管理员 · 永久会员',member_expired:'会员已过期'}[status] || '开通爆款情报会员');
  };
  async function status() {
    const r = await fetch('/api/viral-insights/membership', {credentials:'same-origin', cache:'no-store'});
    if (!r.ok) throw new Error('会员状态读取失败');
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
  async function open() {
    try { await status(); } catch { alert('会员状态读取失败，请检查网络后重试'); return; }
    const node = modal(); if (!node) return;
    node.hidden = false; node.querySelector('[data-vi-modal-title]').textContent = text(state.data?.status, state.data);
    const body = node.querySelector('[data-vi-modal-body]');
    const d = state.data || {};
    body.innerHTML = d.status === 'owner_permanent'
      ? '<p>管理员账号已拥有低粉爆文和低分爆图永久查看权益。导出和实时刷新仍按积分计费。</p>'
      : d.status === 'logged_out'
      ? '<p>登录后可选择开启一次 5 小时免费试用；不点击不会开始计时，也不会自动扣费。</p><button class="vi-primary" data-vi-login>登录 / 注册</button>'
      : `${d.pending_order ? `<p class="vi-pending">订单 ${esc(d.pending_order.out_trade_no)} 待支付。${d.status === 'trial_active' ? '当前可查看完整内容是因为试用仍在有效期内，订单未付款不会开通付费会员。' : d.status === 'member_active' ? '当前可查看完整内容是因为已有会员权益仍然有效。' : '未付款不会开通会员。'}付款完成后稍候刷新。</p>` : ''}
         <p>低粉爆文和低分爆图共用一份权益，可查看完整榜单、筛选和原文。数据以页面标注的榜单日期为准。</p><p>${d.status === 'trial_available' ? '主动开启后开始计时，共 5 小时；不自动扣费。' : '会员到期后立即失效；有效期内续费自动顺延。'}</p>
         ${d.status === 'trial_available' ? '<button class="vi-primary" data-vi-trial>免费试用 5 小时</button>' : ''}
         <div class="vi-packages">${state.packages.map(p => `<button data-vi-package="${esc(p.id)}"><b>${esc(p.name)}</b><span>¥${esc(p.price)} / ${p.days}天</span></button>`).join('')}</div>`;
    node.querySelector('[data-vi-login]')?.addEventListener('click', () => {
      node.hidden = true;
      if (typeof showAuth === 'function') { showAuth(true); setAuthMode('login'); }
      else location.href = '/?register=1';
    });
    node.querySelectorAll('[data-vi-trial]').forEach(b => b.onclick = async () => {
      b.disabled = true;
      try {
      const r = await fetch('/api/viral-insights/trial/activate', {method:'POST', credentials:'same-origin'});
      if (!r.ok) { const p = await r.json().catch(() => ({})); alert(p.detail || '试用激活失败'); b.disabled = false; return; }
      await status(); node.hidden = true;
      window.LowfansView?.reload?.(); window.ImageBoardView?.reload?.();
      } catch { alert('网络异常，请稍后重试'); b.disabled = false; }
    });
    node.querySelectorAll('[data-vi-package]').forEach(b => b.onclick = () => buy(b.dataset.viPackage));
  }
  async function buy(packageId) {
    if (state.buying) return;
    state.buying = true;
    try {
    const r = await fetch('/api/viral-insights/orders', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json'}, body:JSON.stringify({package_id:packageId})});
    const data = await r.json();
    if (!r.ok) { alert(data.detail || '暂时无法创建订单'); return; }
    const holder = document.createElement('div'); holder.innerHTML = data.form_html; document.body.appendChild(holder); holder.querySelector('form')?.submit();
    } catch { alert('网络异常，请稍后重试'); } finally { state.buying = false; }
  }
  window.ViralInsightsMembership = { status, open };
  document.addEventListener('click', e => { if (e.target.closest('[data-viral-insights-open]')) open(); if (e.target.closest('[data-vi-close]')) modal().hidden = true; });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && modal() && !modal().hidden) modal().hidden = true; });
  document.addEventListener('DOMContentLoaded', () => { status().catch(() => {}); });
  window.addEventListener('account-changed', () => status().then(() => {
    window.LowfansView?.reload?.(); window.ImageBoardView?.reload?.();
  }).catch(() => {}));
})();
