/* Home entry points. Resource pages use ordinary, shareable URLs. */
(() => {
  const date = document.querySelector('.hv-date');
  if (date) date.textContent = new Intl.DateTimeFormat('zh-CN', {dateStyle:'full'}).format(new Date());
  const draft = document.querySelector('#atelier-draft');
  const start = document.querySelector('#atelier-start-go');
  if (!draft || !start) return;
  // 公众号创作的入口已隐藏，快捷区默认落到小红书；恢复时把这一行改回 '/workbench'，
  // 并在 index.html 里把「公众号」chip 放回来。
  let target = '/xiaohongshu';
  const chips = [...document.querySelectorAll('.hv-chip')];
  chips.forEach(chip => chip.addEventListener('click', () => {
    target = chip.dataset.target;
    chips.forEach(item => {
      const selected = item === chip;
      item.classList.toggle('is-on', selected); item.setAttribute('aria-pressed', String(selected));
    });
    start.href = target;
  }));
  const forward = event => {
    if (event && (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button > 0)) return;
    event?.preventDefault();
    const value = draft.value.trim();
    if (value) {
      if (target === '/workbench') sessionStorage.setItem('universe.homeDraft', value);
      else sessionStorage.setItem('universe.creatorHomeDraft', JSON.stringify({target, text:value}));
    }
    window.location.assign(target);
  };
  start.addEventListener('click', forward);
  draft.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) forward(event);
  });
  const recent = document.querySelector('#home-recent-list');
  if (!recent) return;
  const message = text => { recent.replaceChildren(); const p = document.createElement('p'); p.className = 'hv-empty'; p.textContent = text; recent.append(p); };
  let recentRequest = 0;
  async function loadRecent() {
    const request = ++recentRequest;
    try {
      const response = await fetch('/api/conversations?limit=50');
      if (request !== recentRequest) return;
      if (response.status === 401) { message('登录后查看最近的公众号创作。'); return; }
      if (!response.ok) throw new Error('load failed');
      const data = await response.json();
      if (request !== recentRequest) return;
      const items = (data.conversations || []).filter(item => item.skill_id === 'wechat_writer').slice(0, 3);
      if (!items.length) { message('暂无最近的公众号创作记录，从一个选题开始吧。'); return; }
      recent.replaceChildren();
      for (const item of items) {
        const link = document.createElement('a'); link.className = 'hv-row';
        link.href = `/workbench?conversation=${encodeURIComponent(item.id)}`;
        const text = document.createElement('span'); text.className = 'txt';
        const title = document.createElement('b'); title.textContent = item.title || '未命名创作';
        const time = document.createElement('span'); const updated = new Date(item.updated_at);
        time.textContent = Number.isNaN(updated.getTime()) ? '公众号创作' : new Intl.DateTimeFormat('zh-CN', {dateStyle:'medium', timeStyle:'short'}).format(updated);
        text.append(title, time); link.append(text); recent.append(link);
      }
    } catch { if (request === recentRequest) message('暂时无法读取记录，可前往创作台查看历史。'); }
  }
  loadRecent();
  window.addEventListener('account-changed', () => { message('正在读取最近创作…'); loadRecent(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) loadRecent(); });
})();
