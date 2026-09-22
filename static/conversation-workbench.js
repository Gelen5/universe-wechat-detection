(() => {
  'use strict';

  const root = document.querySelector('#workbench.normalized-conversation');
  if (!root) return;
  const thread = root.querySelector('#workbench-chat-thread');
  const input = root.querySelector('#workbench-topic');
  const send = root.querySelector('#start-workbench');
  const status = root.querySelector('#workbench-status');
  const editor = root.querySelector('#article-editor');
  const title = root.querySelector('#result-title');
  const saveState = root.querySelector('#article-save-state');
  const versionLabel = root.querySelector('#article-version-label');
  const changeLabel = root.querySelector('#article-change-label');
  const artifactList = root.querySelector('#workbench-version-list');
  const resultMeta = root.querySelector('#result-meta');
  const progress = root.querySelector('#workbench-progress');
  const progressTitle = root.querySelector('#workbench-progress-title');
  const progressDetail = root.querySelector('#workbench-progress-detail');
  const progressBar = root.querySelector('#workbench-progress-bar');
  const cancel = root.querySelector('#cancel-workbench');
  const images = root.querySelector('#generated-images');
  const modeButtons = [...root.querySelectorAll('.mode-option')];
  const historyPopover = root.querySelector('#workbench-chat-history');
  const keyConversation = 'universe.conversation.workbench';
  const keyRun = 'universe.conversation.activeRun';
  let conversation = null;
  let activeRun = null;
  let source = null;
  let selectedMode = 'manual';
  let renderedEventIds = new Set();
  let currentArtifact = null;
  let editableArtifacts = [];
  let artifactIndex = -1;
  let saveTimer = null;
  let editSequence = 0;
  // Lock before the async conversation creation/request starts. Waiting for
  // the API response here would allow rapid clicks to create duplicate runs.
  let submitting = false;

  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));

  async function api(path, options = {}) {
    const response = await fetch(path, options);
    const type = response.headers.get('content-type') || '';
    const data = type.includes('application/json') ? await response.json() : { detail: await response.text() };
    if (!response.ok) throw new Error(data.detail || `请求失败（${response.status}）`);
    return data;
  }

  function uuid() {
    return globalThis.crypto?.randomUUID?.() || `run-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function setBusy(value, label = '') {
    send.disabled = value;
    cancel.disabled = !value;
    input.disabled = value;
    progress.hidden = !value;
    progress.style.display = value ? '' : 'none';
    if (value) {
      progressTitle.textContent = label || '正在处理你的请求';
      progressDetail.textContent = '任务在后台执行，刷新页面也不会丢失';
      progressBar.style.width = '42%';
    }
  }

  function renderMessages(messages) {
    thread.innerHTML = messages.length ? messages.map(message => `
      <article class="chat-message ${message.role === 'user' ? 'from-user' : 'from-ai'}">
        <span>${message.role === 'user' ? '你' : message.role === 'tool' ? '工具' : 'AI 共创助手'}</span>
        <p>${escapeHtml(message.content)}</p>
      </article>`).join('') : `
      <article class="chat-message from-ai"><span>AI 共创助手</span>
        <p>告诉我你想完成什么。我会选择能力、执行工具，并把作品保存在右侧。</p>
      </article>`;
    thread.scrollTop = thread.scrollHeight;
  }

  function appendProgress(text, eventId = '') {
    if (eventId && renderedEventIds.has(eventId)) return;
    if (eventId) renderedEventIds.add(eventId);
    thread.insertAdjacentHTML('beforeend', `
      <article class="chat-message from-ai tool-progress"><span>执行进度</span><p>${escapeHtml(text)}</p></article>`);
    thread.scrollTop = thread.scrollHeight;
  }

  const eventText = (type, payload) => ({
    'run.created': '任务已经创建', 'run.queued': '任务正在排队', 'run.started': '正在理解你的需求',
    'run.running': '正在调用专业 Skill', 'skill.selected': `已选择 ${payload.skill_id || '合适的 Skill'}`,
    'tool.started': `正在执行 ${payload.tool_name || '工具'}`,
    'tool.completed': `${payload.tool_name || '工具'}执行完成`,
    'tool.failed': `${payload.tool_name || '工具'}执行失败`,
    'artifact.created': '作品已经生成', 'artifact.updated': '作品已生成新版本',
    'assistant.completed': '回复与作品已保存', 'run.completed': '本轮已完成',
    'run.failed': '本轮执行失败，已按规则退还积分', 'run.cancelled': '任务已取消',
    'run.waiting_input': '还需要你补充一点信息',
  }[type] || '任务状态已更新');

  function artifactKind(item) {
    return ({ article: '文章', outline: '框架', topic: '选题', image: '图片', report: '报告', html: 'HTML', markdown: 'Markdown' })[item.type] || item.type;
  }

  function showArtifact(item) {
    if (!item) return;
    currentArtifact = item;
    artifactIndex = editableArtifacts.findIndex(candidate => candidate.id === item.id);
    title.textContent = item.title || artifactKind(item);
    editor.value = item.content || '';
    editor.readOnly = item.type === 'image';
    versionLabel.textContent = `${artifactKind(item)} · V${item.version}`;
  }

  function renderArtifacts(artifacts) {
    const ordered = [...artifacts].sort((a, b) =>
      String(a.updated_at || a.created_at || '').localeCompare(String(b.updated_at || b.created_at || '')));
    editableArtifacts = ordered.filter(item => ['article', 'markdown', 'html', 'report', 'topic'].includes(item.type));
    const current = editableArtifacts.at(-1) || ordered.at(-1);
    if (!current) {
      currentArtifact = null;
      title.textContent = '作品会在这里出现'; editor.value = '';
      editor.readOnly = true;
      artifactList.innerHTML = '<p class="empty-artifact">当前对话还没有作品</p>';
      return;
    }
    showArtifact(current);
    saveState.textContent = '已保存到当前对话';
    versionLabel.textContent = `${artifactKind(current)} · V${current.version}`;
    changeLabel.textContent = '每次修改都会保留历史版本';
    resultMeta.textContent = `${artifactKind(current)} · ${ordered.length} 个版本`;
    artifactList.innerHTML = ordered.slice().reverse().map(item => `
      <button class="version-item${item.id === current.id ? ' current' : ''}" data-artifact-id="${escapeHtml(item.id)}" type="button">
        <strong>${escapeHtml(artifactKind(item))} V${item.version}</strong><span>${escapeHtml(item.title || '未命名作品')}</span>
      </button>`).join('');
    artifactList.querySelectorAll('[data-artifact-id]').forEach(button => button.addEventListener('click', () => {
      const item = ordered.find(candidate => candidate.id === button.dataset.artifactId);
      if (!item) return;
      showArtifact(item);
    }));
    const imageArtifacts = ordered.filter(item => item.type === 'image' && item.storage_url);
    images.hidden = !imageArtifacts.length;
    images.innerHTML = imageArtifacts.length ? `<div class="image-grid">${imageArtifacts.map(item => `
      <a href="${escapeHtml(item.storage_url)}" target="_blank" rel="noopener"><img src="${escapeHtml(item.storage_url)}" alt="${escapeHtml(item.title || '生成图片')}"><span><strong>${escapeHtml(item.title || '生成图片')}</strong><small>V${item.version}</small></span></a>`).join('')}</div>` : '';
  }

  async function refresh() {
    if (!conversation) return;
    const [messages, artifacts] = await Promise.all([
      api(`/api/conversations/${encodeURIComponent(conversation.id)}/messages`),
      api(`/api/conversations/${encodeURIComponent(conversation.id)}/artifacts`),
    ]);
    renderMessages(messages.messages || []); renderArtifacts(artifacts.artifacts || []);
  }

  async function saveArtifactEdit(sequence, artifact, content) {
    try {
      const data = await api(`/api/artifacts/${encodeURIComponent(artifact.id)}/versions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
      });
      if (sequence !== editSequence) return;
      currentArtifact = data.artifact;
      saveState.textContent = '已保存新版本';
      await refresh();
    } catch (error) {
      if (sequence === editSequence) saveState.textContent = `保存失败：${error.message}`;
    }
  }

  async function ensureConversation() {
    if (conversation) return conversation;
    const payload = selectedMode === 'auto'
      ? { mode: 'auto', title: 'AI 创作对话' }
      : { mode: 'manual', skill_id: 'wechat_writer', title: '公众号创作' };
    const data = await api('/api/conversations', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    conversation = data.conversation;
    localStorage.setItem(keyConversation, conversation.id);
    return conversation;
  }

  async function openConversation(conversationId) {
    closeEvents(); activeRun = null; localStorage.removeItem(keyRun);
    conversation = (await api(`/api/conversations/${encodeURIComponent(conversationId)}`)).conversation;
    selectedMode = conversation.mode;
    modeButtons.forEach(button => button.classList.toggle(
      'active', (button.dataset.mode === 'auto') === (selectedMode === 'auto'),
    ));
    localStorage.setItem(keyConversation, conversation.id);
    historyPopover.hidden = true;
    await refresh();
    status.textContent = '已恢复历史对话';
  }

  async function toggleConversationHistory() {
    if (!historyPopover.hidden) { historyPopover.hidden = true; return; }
    historyPopover.hidden = false;
    historyPopover.innerHTML = '<p class="empty-artifact">正在读取最近对话…</p>';
    try {
      const rows = (await api('/api/conversations?limit=20')).conversations || [];
      historyPopover.innerHTML = rows.length ? rows.map(item => `
        <button type="button" data-conversation-id="${escapeHtml(item.id)}" class="${item.id === conversation?.id ? 'current' : ''}">
          <strong>${escapeHtml(item.title || '新对话')}</strong>
          <small>${escapeHtml(item.mode === 'auto' ? '自动选择' : '公众号创作')} · ${escapeHtml(new Date(item.updated_at).toLocaleString())}</small>
        </button>`).join('') : '<p class="empty-artifact">还没有历史对话</p>';
    } catch (error) { historyPopover.innerHTML = `<p class="empty-artifact">${escapeHtml(error.message)}</p>`; }
  }

  function closeEvents() { source?.close(); source = null; }

  function watchRun(runId) {
    closeEvents(); activeRun = runId; localStorage.setItem(keyRun, runId);
    setBusy(true, 'AI 正在调用 Skill');
    source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
    const types = ['run.created', 'run.queued', 'run.started', 'run.running', 'run.waiting_input',
      'skill.selected', 'tool.started', 'tool.completed', 'tool.failed', 'artifact.created',
      'artifact.updated', 'assistant.completed', 'run.completed', 'run.failed', 'run.cancelled'];
    types.forEach(type => source.addEventListener(type, async event => {
      let payload = {};
      try { payload = JSON.parse(event.data || '{}').payload || {}; } catch { /* non-fatal */ }
      appendProgress(eventText(type, payload), event.lastEventId); status.textContent = eventText(type, payload);
      if (['run.completed', 'run.failed', 'run.cancelled', 'run.waiting_input'].includes(type)) {
        closeEvents(); activeRun = null; localStorage.removeItem(keyRun); setBusy(false);
        await refresh().catch(error => appendProgress(error.message));
      }
    }));
    source.onerror = async () => {
      try {
        const run = (await api(`/api/runs/${encodeURIComponent(runId)}`)).run;
        if (['completed', 'failed', 'cancelled', 'waiting_input'].includes(run.status)) {
          closeEvents(); activeRun = null; localStorage.removeItem(keyRun); setBusy(false); await refresh();
        }
      } catch { /* persisted replay handles transient disconnects */ }
    };
  }

  async function submit() {
    const content = input.value.trim();
    if (!content || send.disabled || submitting) return;
    submitting = true;
    setBusy(true, '正在提交你的消息');
    const idempotencyKey = uuid();
    try {
      await ensureConversation();
      input.value = '';
      appendProgress('正在提交你的消息');
      const data = await api(`/api/conversations/${encodeURIComponent(conversation.id)}/messages`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ content }),
      });
      await refresh(); watchRun(data.run_id);
    } catch (error) {
      setBusy(false);
      appendProgress(error.message);
    } finally {
      submitting = false;
    }
  }

  async function restore() {
    localStorage.removeItem('universe.activeWorkflowId');
    const conversationId = localStorage.getItem(keyConversation);
    if (conversationId) {
      try {
        conversation = (await api(`/api/conversations/${encodeURIComponent(conversationId)}`)).conversation;
        selectedMode = conversation.mode;
        modeButtons.forEach(button => button.classList.toggle('active', (button.dataset.mode === 'auto') === (selectedMode === 'auto')));
        await refresh();
      } catch { conversation = null; localStorage.removeItem(keyConversation); }
    } else { renderMessages([]); renderArtifacts([]); }
    const runId = localStorage.getItem(keyRun);
    if (runId && conversation) {
      try {
        const run = (await api(`/api/runs/${encodeURIComponent(runId)}`)).run;
        if (['queued', 'running'].includes(run.status)) watchRun(run.id); else localStorage.removeItem(keyRun);
      } catch { localStorage.removeItem(keyRun); }
    }
  }

  function captureClick(selector, handler) {
    document.addEventListener('click', event => {
      const target = event.target.closest(selector);
      if (!target || !root.contains(target)) return;
      event.preventDefault(); event.stopImmediatePropagation(); handler(target, event);
    }, true);
  }

  captureClick('#start-workbench', () => submit());
  captureClick('#new-workbench-chat', () => {
    closeEvents(); conversation = null; activeRun = null; renderedEventIds = new Set();
    localStorage.removeItem(keyConversation); localStorage.removeItem(keyRun);
    submitting = false; setBusy(false); input.value = ''; renderMessages([]); renderArtifacts([]); status.textContent = '等待你的想法';
  });
  captureClick('#recent-workbench-chats', () => toggleConversationHistory());
  captureClick('[data-conversation-id]', button => openConversation(button.dataset.conversationId));
  captureClick('#cancel-workbench', async () => {
    if (!activeRun) return;
    try { await api(`/api/runs/${encodeURIComponent(activeRun)}/cancel`, { method: 'POST' }); }
    catch (error) { appendProgress(error.message); }
  });
  captureClick('#workbench-regenerate-topics', () => {
    input.value = '请重新给我 10 个更具体的选题方向，并说明每个方向为什么值得写。'; input.focus();
  });
  captureClick('.mode-option', button => {
    if (conversation || activeRun) return;
    selectedMode = button.dataset.mode === 'auto' ? 'auto' : 'manual';
    modeButtons.forEach(item => item.classList.toggle('active', item === button));
  });
  captureClick('[data-rewrite-selection]', button => {
    const selection = editor.value.slice(editor.selectionStart, editor.selectionEnd).trim();
    input.value = selection ? `${button.dataset.rewriteSelection}：\n\n${selection}` : button.dataset.rewriteSelection;
    input.focus();
  });
  captureClick('#version-back', () => {
    if (!editableArtifacts.length) return;
    showArtifact(editableArtifacts[Math.max(0, artifactIndex - 1)]);
  });
  captureClick('#version-forward', () => {
    if (!editableArtifacts.length) return;
    showArtifact(editableArtifacts[Math.min(editableArtifacts.length - 1, artifactIndex + 1)]);
  });
  captureClick('#edit-current', () => {
    if (!currentArtifact || editor.readOnly) return;
    editor.focus();
  });
  captureClick('#copy-current-artifact', async () => {
    if (!currentArtifact) return;
    try {
      await navigator.clipboard.writeText(editor.value || currentArtifact.content || '');
      saveState.textContent = '已复制当前作品';
    } catch { saveState.textContent = '浏览器未允许复制'; }
  });
  captureClick('#download-current-artifact', () => {
    if (!currentArtifact) return;
    const extension = currentArtifact.type === 'html' ? 'html' : currentArtifact.type === 'markdown' ? 'md' : 'txt';
    const blob = new Blob([editor.value || currentArtifact.content || ''], {
      type: currentArtifact.type === 'html' ? 'text/html;charset=utf-8' : 'text/plain;charset=utf-8',
    });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${currentArtifact.title || 'artifact'}.${extension}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 0);
  });
  input.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    event.preventDefault(); event.stopImmediatePropagation(); submit();
  }, true);
  editor.addEventListener('input', () => {
    if (!currentArtifact || editor.readOnly || editor.value === (currentArtifact.content || '')) return;
    clearTimeout(saveTimer);
    const sequence = ++editSequence;
    const artifact = currentArtifact;
    const content = editor.value;
    saveState.textContent = '正在保存修改…';
    saveTimer = setTimeout(() => saveArtifactEdit(sequence, artifact, content), 900);
  });

  root.querySelector('#workflow-steps')?.setAttribute('hidden', '');
  root.querySelector('.studio-switch')?.setAttribute('hidden', '');
  root.querySelector('#workbench-decision')?.setAttribute('hidden', '');
  root.querySelector('.flow-actionbar')?.setAttribute('hidden', '');
  restore();
})();
