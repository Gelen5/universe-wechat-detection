(() => {
  const cards = [...document.querySelectorAll('[data-checkin]')];
  if (!cards.length) return;
  let checked = false, pending = false, sequence = 0, signedIn = false, unavailable = false;
  function paint(message = '') {
    cards.forEach(card => {
      const button = card.querySelector('[data-checkin-button]');
      const detail = card.querySelector('[data-checkin-detail]');
      const feedback = card.querySelector('[data-checkin-message]');
      button.disabled = pending || checked;
      button.textContent = pending ? '签到中…' : checked ? '今日已签到' : unavailable ? '重试' : signedIn ? '签到领 5 分' : '登录后签到';
      detail.textContent = checked ? '明天再来，继续领取' : '每天领取 5 积分';
      feedback.textContent = message;
      card.classList.toggle('is-checked', checked);
    });
  }
  async function load() {
    const current = ++sequence;
    try {
      const response = await fetch('/api/checkin', {credentials:'same-origin', cache:'no-store'});
      if (current !== sequence) return;
      if (response.status === 401) { signedIn = false; checked = false; unavailable = false; paint(); return; }
      if (!response.ok) throw new Error('签到状态暂不可用');
      const data = await response.json();
      if (current !== sequence) return;
      signedIn = true; unavailable = false; checked = !!data.checked_in; paint();
    } catch { if (current === sequence) { unavailable = true; checked = false; paint('签到状态暂不可用，请稍后重试'); } }
  }
  cards.forEach(card => card.querySelector('[data-checkin-button]').addEventListener('click', async () => {
    if (pending || checked) return;
    if (unavailable) { load(); return; }
    if (!signedIn) {
      if (typeof showAuth === 'function') showAuth(true);
      else location.href = '/';
      return;
    }
    pending = true; paint();
    const requestSequence = sequence;
    try {
      const response = await fetch('/api/checkin', {method:'POST', credentials:'same-origin'});
      const data = await response.json();
      if (sequence !== requestSequence) return;
      if (response.status === 401) { signedIn = false; throw new Error('请先登录后签到'); }
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '签到未完成，请重试');
      checked = !!data.checked_in;
      if (typeof renderWallet === 'function') renderWallet(data.wallet);
      if (typeof refreshWallet === 'function') refreshWallet().catch(() => {});
      if (location.pathname === '/wallet') { try { sessionStorage.setItem('daily-checkin-credited', data.credited ? '1' : '0'); } catch {} location.reload(); return; }
      paint(data.credited ? '+5 积分已到账' : '今天已经签到');
    } catch (error) { if (sequence === requestSequence) paint(error.message || '签到未完成，请重试'); }
    finally { pending = false; paint(cards[0].querySelector('[data-checkin-message]').textContent); }
  }));
  window.addEventListener('account-changed', () => { checked = false; load(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  setInterval(() => { if (!document.hidden && !pending) load(); }, 60000);
  paint(); load().then(() => { try { const flag = sessionStorage.getItem('daily-checkin-credited'); if (flag !== null) { sessionStorage.removeItem('daily-checkin-credited'); paint(flag === '1' ? '+5 积分已到账' : '今天已经签到'); } } catch {} });
})();
