(() => {
  const hooks = {}, beforeHooks = {};
  function register(name, callback, beforeOpen) { hooks[name] = callback; beforeHooks[name] = beforeOpen; }
  async function open(name) {
    const endpoints = {'tie-tu':'/api/creator/history?skill=tie-tu', 'viral-remix':'/api/creator/history?skill=viral-remix', 'article-visual':'/api/article-visual/history/list'};
    const dialog = document.querySelector('#creation-history-dialog'), content = dialog.querySelector('[data-history-content]');
    dialog.querySelector('h2').textContent = '历史创作'; content.textContent = '正在加载…'; dialog.showModal();
    async function load(before = '') {
    try {
      const response = await fetch(endpoints[name] + (before ? (endpoints[name].includes('?') ? '&' : '?') + 'before=' + encodeURIComponent(before) : ''), {credentials:'same-origin',cache:'no-store'});
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || '加载失败');
      if (!before) content.replaceChildren();
      if (!data.items.length && !before) { content.textContent = '暂时没有创作记录。'; return; }
      for (const item of data.items) {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'creation-history-item';
        const title = document.createElement('strong'); title.textContent = item.title || '未命名创作';
        const info = document.createElement('small'); const date = new Date(item.updated_at); info.textContent = (Number.isNaN(date.valueOf()) ? '' : date.toLocaleString('zh-CN', {timeZone:'Asia/Shanghai'})) + (item.kind === 'chat' ? ' · 对话' : item.kind === 'plan' ? ' · 图文计划' : item.image_count != null ? ` · ${item.image_count} 张图片` : ' · 拆解');
        button.append(title, info); button.onclick = async () => {
          button.disabled = true;
          try { if (await hooks[name]?.(item) !== false) dialog.close(); }
          catch (error) { content.prepend(document.createTextNode(error.message)); }
          finally { button.disabled = false; }
        }; content.append(button);
      }
      if (data.next_before) { const more = document.createElement('button'); more.type = 'button'; more.textContent = '加载更多'; more.onclick = () => { more.remove(); load(data.next_before); }; content.append(more); }
    } catch (error) { if (!before) content.textContent = error.message || '加载失败，请稍后重试。'; else content.append(document.createTextNode('加载更多失败，请重新打开重试。')); }
    }
    try { if (beforeHooks[name]) await beforeHooks[name](); await load(); }
    catch (error) { content.textContent = error.message || '加载失败，请稍后重试。'; }
  }
  document.querySelector('#creation-history-close').onclick = () => document.querySelector('#creation-history-dialog').close();
  document.querySelectorAll('[data-creation-history]').forEach(button => { button.onclick = () => open(button.dataset.creationHistory); });
  window.CreationHistory = {register, open};
})();
