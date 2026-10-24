export function setupSelection({ $, api, task, backup, capabilities }) {
  const modes = ['ai', 'hot', 'custom', 'rewrite'];
  const price = capabilities.pricing.find(item => item.path === '/api/qihaoshou/topics')?.points;
  $('q-topics-refresh').textContent = '生成选题 · ' + (price ?? 3) + '积分';
  const tabs = [...document.querySelectorAll('[data-mode]')];
  const styleButtons = $('q-style-buttons');
  styleButtons.replaceChildren();
  for (const style of capabilities.styles) {
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = style.name; button.dataset.style = style.id;
    button.title = style.description; button.setAttribute('aria-pressed', 'false');
    button.onclick = () => { $('q-style').value = style.id; sync(); backup(); };
    styleButtons.append(button);
  }
  function sync() {
    const mode = modes.includes($('q-mode').value) ? $('q-mode').value : 'custom';
    $('q-mode').value = mode;
    for (const tab of tabs) {
      const active = tab.dataset.mode === mode;
      tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1;
      $('q-panel-' + tab.dataset.mode).hidden = !active;
    }
    if (mode === 'rewrite') $('q-reference-details').open = true;
    for (const button of styleButtons.children) button.setAttribute('aria-pressed', String(button.dataset.style === $('q-style').value));
    $('q-style-description').textContent = capabilities.styles.find(x => x.id === $('q-style').value)?.description || '';
    $('q-selection-note').textContent = $('q-source_notes').value ? '已带入来源线索；摘要不是全文核验，请先检查原文。' : '';
  }
  for (const tab of tabs) {
    tab.onclick = () => { $('q-mode').value = tab.dataset.mode; sync(); backup(); };
    tab.onkeydown = event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault(); const index = tabs.indexOf(tab);
      const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs.at(-1) : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
      next.click(); next.focus();
    };
  }
  $('q-style').addEventListener('change', sync);
  function sourceLines(sources) {
    return sources.map(source => `${source.title}\n来源：${source.url}\n发布时间：${source.published_at || '未知'}\n摘要（未核实）：${source.excerpt || ''}`).join('\n\n').slice(0, 6000);
  }
  function renderCards(target, items, mode) {
    $(target).replaceChildren();
    for (const item of items) {
      const card = document.createElement('article'); card.className = 'topic-card';
      const heading = document.createElement('h4'); heading.textContent = item.title; card.append(heading);
      const detail = document.createElement('p'); detail.textContent = mode === 'ai' ? `${item.kind} · ${item.angle}\n${item.reason}` : `${item.provider} · ${new Date(item.published_at).toLocaleString('zh-CN')}\n${item.excerpt || ''}`;
      card.append(detail);
      const sources = mode === 'hot' ? [item] : item.sources;
      for (const source of sources || []) {
        const link = document.createElement('a'); link.textContent = '查看来源：' + source.title;
        try { const url = new URL(source.url); if (url.protocol !== 'https:' || url.username || url.password) continue; link.href = url.href; } catch { continue; }
        link.target = '_blank'; link.rel = 'noopener noreferrer'; card.append(link);
      }
      const choose = document.createElement('button'); choose.type = 'button'; choose.textContent = '用这个选题写作';
      choose.onclick = () => {
        $('q-topic').value = item.title; $('q-angle').value = mode === 'ai' ? item.angle : '围绕这条资讯解释背景、影响和待核实的问题';
        $('q-outline').value = item.outline || ''; $('q-source_notes').value = sourceLines(sources || []);
        $('q-mode').value = mode; sync(); backup();
        document.querySelectorAll('.topic-card').forEach(node => node.classList.remove('selected'));
        card.classList.add('selected'); $('q-selection-note').textContent = '已选：' + item.title + '。可调整角度与大纲，再开始写作。';
      };
      card.append(choose); $(target).append(card);
    }
  }
  $('q-topics-refresh').onclick = () => task(async () => {
    $('q-topics-notice').textContent = '正在检索线索并生成选题…';
    try {
      const result = await api('/topics', { method: 'POST', body: JSON.stringify({direction: $('q-topic-direction').value, audience: $('q-audience').value, style: $('q-style').value, research: $('q-topic-research').checked}) });
      renderCards('q-topic-cards', result.items, 'ai'); $('q-topics-notice').textContent = result.notice;
    } catch (error) { $('q-topics-notice').textContent = error.message; throw error; }
  });
  $('q-hot-refresh').onclick = () => task(async () => {
    $('q-hot-notice').textContent = '正在获取近72小时资讯…';
    try {
      const params = new URLSearchParams({direction: $('q-hot-direction').value, category: $('q-hot-category').value});
      const result = await api('/hotspots?' + params);
      renderCards('q-hot-cards', result.items, 'hot'); $('q-hot-notice').textContent = result.notice + ' 获取时间：' + new Date(result.checked_at).toLocaleString('zh-CN');
    } catch (error) { $('q-hot-notice').textContent = error.message; throw error; }
  });
  $('q-theme-preview').onclick = () => task(async () => {
    const result = await api('/themes/preview', {method: 'POST', body: JSON.stringify({theme: $('q-theme').value})});
    $('q-theme-preview-frame').srcdoc = result.html; $('q-preview-dialog').showModal();
  });
  $('q-preview-close').onclick = () => $('q-preview-dialog').close();
  return sync;
}
