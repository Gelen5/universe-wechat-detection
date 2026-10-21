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
  const skillPicker = root.querySelector('#workbench-skill-picker');
  const viewToggle = root.querySelector('#workbench-view-toggle');
  const historyPopover = root.querySelector('#workbench-chat-history');
  const stageNav = root.querySelector('#workbench-stage-nav');
  const stageTitle = root.querySelector('#workbench-stage-title');
  const stageHint = root.querySelector('#workbench-stage-hint');
  const stageKicker = root.querySelector('#workbench-stage-kicker');
  const stageNext = root.querySelector('#workbench-stage-next');
  const stageRerun = root.querySelector('#workbench-stage-rerun');
  const stageChoices = root.querySelector('#workbench-stage-choices');
  const htmlPreview = root.querySelector('#workbench-html-preview');
  const keyConversation = 'universe.conversation.workbench';
  const keyRun = 'universe.conversation.activeRun';
  const stageKey = id => `universe.conversation.stage.${id}`;
  const stages = [
    { id: 'topic', label: '选题', hint: '输入主题，选择一个值得写的方向。' },
    { id: 'outline', label: '大纲', hint: '确认文章结构；可以直接修改大纲。' },
    { id: 'writing', label: '写作', hint: '根据确认的大纲生成正文。' },
    { id: 'deai', label: '去 AI', hint: '保留原意，检查事实与表达并生成修订稿。' },
    { id: 'typeset', label: '排版', hint: '用最新正文生成公众号 HTML 预览。' },
  ];
  let conversation = null;
  let activeRun = null;
  let source = null;
  let selectedMode = 'manual';
  let selectedSkill = 'wechat_writer';
  let renderedEventIds = new Set();
  let currentArtifact = null;
  let outputOpen = false;
  let editableArtifacts = [];
  let artifactIndex = -1;
  let saveTimer = null;
  let editSequence = 0;
  // Lock before the async conversation creation/request starts. Waiting for
  // the API response here would allow rapid clicks to create duplicate runs.
  let submitting = false;
  let activeStage = 'topic';
  let allArtifacts = [];
  let selectedTopic = '';
  let brief = '';

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
    renderStage();
  }

  function renderMessages(messages) {
    const firstBrief = messages.find(message => message.role === 'user' &&
      message.content_json?.workflow_stage === 'topic');
    if (firstBrief) brief = firstBrief.content;
    thread.innerHTML = messages.length ? messages.map(message => `
      <article class="chat-message ${message.role === 'user' ? 'from-user' : 'from-ai'}">
        <span>${message.role === 'user' ? '你' : message.role === 'tool' ? '工具' : 'AI 共创助手'}</span>
        <p>${escapeHtml(message.content)}</p>
      </article>`).join('') : `
      <article class="chat-message from-ai"><span>创作助手</span>
        <p>输入一个主题，先从选题开始。之后可以按阶段查看和修改作品。</p>
      </article>`;
    thread.scrollTop = thread.scrollHeight;
  }

  function appendProgress(text, eventId = '') {
    if (eventId && renderedEventIds.has(eventId)) return;
    if (eventId) renderedEventIds.add(eventId);
    status.textContent = text;
  }

  function appendNotice(text) {
    thread.insertAdjacentHTML('beforeend', `
      <article class="chat-message from-ai tool-progress"><span>执行进度</span><p>${escapeHtml(text)}</p></article>`);
    thread.scrollTop = thread.scrollHeight;
  }

  function failureText(payload = {}) {
    const error = String(payload.error_message || '').toLowerCase();
    const kind = payload.error_kind || (
      /ip 不在令牌允许访问|ip is not allowed/.test(error) ? 'provider_access' :
      /额度不足|余额不足|insufficient balance|insufficient_quota/.test(error) ? 'provider_balance' :
      /provider connection failed|remote end closed|connection reset/.test(error) ? 'provider_connection' : '');
    if (kind === 'provider_access') return '文字 API Key 未允许服务器 IP 访问，请联系管理员检查白名单；本轮积分已退还';
    if (kind === 'provider_balance') return '文本 API 额度不足，请联系管理员充值；本轮积分已退还';
    if (kind === 'provider_connection') return '模型服务暂时断开，请稍后重试；本轮积分已退还';
    if (kind === 'queue') return '任务暂时无法进入队列，请稍后重试；积分已退还';
    return '本轮执行失败，已按规则退还积分';
  }

  const eventText = (type, payload) => ({
    'run.created': '任务已经创建', 'run.queued': '任务正在排队', 'run.started': '正在理解你的需求',
    'run.running': '正在处理当前阶段', 'skill.selected': '已开始当前阶段',
    'tool.started': '正在生成当前阶段的成果',
    'tool.completed': '当前阶段的成果已生成',
    'tool.failed': '当前阶段执行失败',
    'artifact.created': '作品已经生成', 'artifact.updated': '作品已生成新版本',
    'assistant.completed': '回复与作品已保存', 'run.completed': '本轮已完成',
    'run.failed': failureText(payload), 'run.cancelled': '任务已取消',
    'run.waiting_input': '还需要你补充一点信息',
  }[type] || '任务状态已更新');

  function artifactKind(item) {
    return ({ article: '文章', outline: '大纲', topic: '选题', image: '图片', report: '复核报告', html: '排版', markdown: 'Markdown' })[item.type] || item.type;
  }

  function setOutputOpen(value) {
    outputOpen = value;
    root.dataset.outputOpen = String(value);
    root.dataset.studioView = value ? 'article' : 'chat';
    viewToggle.textContent = value ? '返回对话' : '查看作品';
    viewToggle.setAttribute('aria-pressed', String(value));
  }

  function latestOf(type, predicate = () => true) {
    return allArtifacts.filter(item => item.type === type && predicate(item)).at(-1) || null;
  }

  function stageArtifact(stage) {
    const report = latestOf('report');
    if (stage === 'topic') return latestOf('topic');
    if (stage === 'outline') return latestOf('outline');
    if (stage === 'writing') return latestOf('article', item => !report || item.run_id !== report.run_id)
      || latestOf('article');
    if (stage === 'deai') return report;
    if (stage === 'typeset') return latestOf('html');
    return null;
  }

  function isStale(stage) {
    const index = stages.findIndex(item => item.id === stage);
    if (index < 1 || !stageArtifact(stage)) return false;
    const previous = stageArtifact(stages[index - 1].id);
    return Boolean(previous && previous.updated_at > stageArtifact(stage).updated_at);
  }

  function selectStage(stage) {
    if (!stages.some(item => item.id === stage)) return;
    activeStage = stage;
    if (conversation) localStorage.setItem(stageKey(conversation.id), stage);
    renderStage();
    if (window.matchMedia('(max-width: 980px)').matches && stageArtifact(stage)) setOutputOpen(true);
  }

  function renderStage() {
    const index = stages.findIndex(item => item.id === activeStage);
    const stage = stages[index] || stages[0];
    const item = stageArtifact(stage.id);
    const stale = isStale(stage.id);
    stageKicker.textContent = `${String(index + 1).padStart(2, '0')} / 05`;
    stageTitle.textContent = stage.label;
    stageHint.textContent = stale ? '上游作品已修改，请更新本阶段结果。' : stage.hint;
    stageNav.innerHTML = stages.map((entry, position) => {
      const done = Boolean(stageArtifact(entry.id));
      const state = isStale(entry.id) ? '需更新' : done ? '已完成' : position === index ? '当前阶段' : '待开始';
      return `<button type="button" data-workbench-stage="${entry.id}" ${position === index ? 'aria-current="step"' : ''}>
        <span>${String(position + 1).padStart(2, '0')} ${entry.label}</span><small>${state}</small></button>`;
    }).join('');
    const editorWrap = editor.closest('.editor-wrap');
    const hasText = item && item.type !== 'html' && stage.id !== 'topic';
    editorWrap.hidden = !hasText;
    htmlPreview.hidden = stage.id !== 'typeset' || !item;
    stageChoices.innerHTML = '';
    if (stage.id === 'typeset' && item) htmlPreview.srcdoc = item.content || '';
    if (stage.id === 'topic' && item) {
      const topics = item.content_json?.topics || [];
      if (Array.isArray(topics) && topics.length) {
        stageChoices.innerHTML = `<strong>选择一个方向</strong>${topics.map((choice, position) => {
          const name = String(typeof choice === 'string' ? choice : choice.title || '').trim();
          return `<button type="button" data-topic-choice="${position}" aria-pressed="${name === selectedTopic}">
            <span>${String(position + 1).padStart(2, '0')}</span>${escapeHtml(name)}</button>`;
        }).join('')}`;
      }
    }
    if (stage.id === 'deai' && item) {
      const revised = latestOf('article', candidate => candidate.run_id === item.run_id);
      showArtifact(revised || item);
      if (item.content_json?.review) {
        stageChoices.innerHTML = `<details><summary>查看复核报告</summary><pre>${escapeHtml(JSON.stringify(item.content_json.review, null, 2))}</pre></details>`;
      }
    } else if (item && hasText) showArtifact(item);
    else {
      currentArtifact = item;
      title.textContent = item?.title || `等待${stage.label}结果`;
      editor.value = '';
      editor.readOnly = true;
      versionLabel.textContent = item ? `${artifactKind(item)} · V${item.version}` : '尚未生成';
    }
    stageRerun.hidden = !item;
    stageRerun.disabled = !progress.hidden;
    stageRerun.textContent = stale ? '更新本阶段' : '重新生成';
    stageNext.hidden = index === stages.length - 1;
    stageNext.textContent = stale ? `更新${stage.label}` : item ? `继续：${stages[index + 1]?.label || ''}` : `生成${stage.label}`;
    stageNext.disabled = Boolean(!progress.hidden || submitting || (stage.id === 'topic' && item && !selectedTopic) ||
      (index > 0 && !stageArtifact(stages[index - 1].id)));
    viewToggle.hidden = !allArtifacts.length;
    resultMeta.textContent = item ? `${artifactKind(item)} · V${item.version}` : '当前阶段尚无作品';
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
    allArtifacts = ordered;
    editableArtifacts = ordered.filter(item => ['article', 'outline', 'markdown', 'html', 'report', 'topic'].includes(item.type));
    const current = editableArtifacts.at(-1) || ordered.at(-1);
    if (!current) {
      currentArtifact = null;
      viewToggle.hidden = true;
      renderStage();
      title.textContent = '作品会在这里出现'; editor.value = '';
      editor.readOnly = true;
      artifactList.innerHTML = '<p class="empty-artifact">当前对话还没有作品</p>';
      return;
    }
    const firstArtifact = !currentArtifact;
    showArtifact(current);
    viewToggle.hidden = false;
    if (firstArtifact) setOutputOpen(false);
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
    renderStage();
  }

  async function refresh() {
    if (!conversation) return;
    const [messages, artifacts] = await Promise.all([
      api(`/api/conversations/${encodeURIComponent(conversation.id)}/messages`),
      api(`/api/conversations/${encodeURIComponent(conversation.id)}/artifacts`),
    ]);
    renderMessages(messages.messages || []); renderArtifacts(artifacts.artifacts || []);
  }

  function stageInstruction(stage, extra = '') {
    const addition = extra.trim() ? `\n补充要求：${extra.trim()}` : '';
    if (stage === 'topic') return `${brief || extra}\n只生成公众号选题，不写正文，不生成图片。${addition}`;
    if (stage === 'outline') return `为已确认选题《${selectedTopic}》生成可编辑的公众号文章大纲。只执行大纲阶段，不写正文。${addition}`;
    if (stage === 'writing') return `根据当前已确认的大纲，为《${selectedTopic || stageArtifact('outline')?.title || '当前选题'}》写完整公众号正文。只执行写作阶段，不生成图片。${addition}`;
    if (stage === 'deai') return `对当前最新正文执行去 AI 味、事实边界和可读性复核，保留原意并保存修订稿。只执行复核阶段。${addition}`;
    return `用当前最新正文重新排版为公众号 HTML，不生成图片、不改写正文。只执行排版阶段。${addition}`;
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
      : { mode: 'manual', skill_id: selectedSkill, title: skillPicker.selectedOptions[0]?.textContent || '公众号创作' };
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
    activeStage = localStorage.getItem(stageKey(conversation.id)) || 'topic';
    selectedTopic = localStorage.getItem(`universe.conversation.topic.${conversation.id}`) || '';
    selectedMode = conversation.mode;
    selectedSkill = conversation.skill_id || 'wechat_writer';
    syncSkillPicker();
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
          <small>${escapeHtml(item.mode === 'auto' ? '自动选择' : item.title || '指定能力')} · ${escapeHtml(new Date(item.updated_at).toLocaleString())}</small>
        </button>`).join('') : '<p class="empty-artifact">还没有历史对话</p>';
    } catch (error) { historyPopover.innerHTML = `<p class="empty-artifact">${escapeHtml(error.message)}</p>`; }
  }

  function closeEvents() { source?.close(); source = null; }

  function watchRun(runId) {
    closeEvents(); activeRun = runId; localStorage.setItem(keyRun, runId);
    setBusy(true, `正在生成${stages.find(item => item.id === activeStage)?.label || '当前成果'}`);
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
        await refresh().catch(error => appendNotice(error.message));
        if (type === 'run.completed' && window.matchMedia('(max-width: 980px)').matches) setOutputOpen(true);
      }
    }));
    source.onerror = async () => {
      try {
        const run = (await api(`/api/runs/${encodeURIComponent(runId)}`)).run;
        if (['completed', 'failed', 'cancelled', 'waiting_input'].includes(run.status)) {
          if (run.status === 'failed') {
            const message = failureText(run);
            appendProgress(message); status.textContent = message;
          }
          closeEvents(); activeRun = null; localStorage.removeItem(keyRun); setBusy(false); await refresh();
        }
      } catch { /* persisted replay handles transient disconnects */ }
    };
  }

  async function submit(content = input.value.trim(), stage = activeStage) {
    if (!content || send.disabled || submitting) return;
    submitting = true;
    if (stage === 'topic' && !brief) brief = content;
    setBusy(true, '正在提交你的消息');
    const idempotencyKey = uuid();
    const draftInput = input.value;
    try {
      await ensureConversation();
      input.value = '';
      appendProgress('正在提交你的消息');
      const data = await api(`/api/conversations/${encodeURIComponent(conversation.id)}/messages`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ content, content_json: { workflow_stage: stage } }),
      });
      await refresh(); watchRun(data.run_id);
    } catch (error) {
      setBusy(false);
      input.value = draftInput;
      appendNotice(error.message);
    } finally {
      submitting = false;
    }
  }

  function runStage(stage, extra = '') {
    if (stage === 'topic' && !brief && !extra.trim()) {
      input.focus(); status.textContent = '请先输入你想写的主题'; return;
    }
    if (stage === 'outline' && !selectedTopic) {
      selectStage('topic'); status.textContent = '请先选择一个选题方向'; return;
    }
    if (stage === 'topic' && stageArtifact('topic')) {
      selectedTopic = '';
      if (conversation) localStorage.removeItem(`universe.conversation.topic.${conversation.id}`);
    }
    selectStage(stage);
    submit(stageInstruction(stage, extra), stage);
  }

  async function restore() {
    localStorage.removeItem('universe.activeWorkflowId');
    const conversationId = localStorage.getItem(keyConversation);
    if (conversationId) {
      try {
        conversation = (await api(`/api/conversations/${encodeURIComponent(conversationId)}`)).conversation;
        activeStage = localStorage.getItem(stageKey(conversation.id)) || 'topic';
        selectedTopic = localStorage.getItem(`universe.conversation.topic.${conversation.id}`) || '';
        selectedMode = conversation.mode;
        selectedSkill = conversation.skill_id || 'wechat_writer';
        syncSkillPicker();
        modeButtons.forEach(button => button.classList.toggle('active', (button.dataset.mode === 'auto') === (selectedMode === 'auto')));
        await refresh();
      } catch { conversation = null; localStorage.removeItem(keyConversation); }
    } else { renderMessages([]); renderArtifacts([]); }
    const runId = localStorage.getItem(keyRun);
    if (runId && conversation) {
      try {
        const run = (await api(`/api/runs/${encodeURIComponent(runId)}`)).run;
        if (['queued', 'running'].includes(run.status)) watchRun(run.id);
        else {
          localStorage.removeItem(keyRun);
          if (run.status === 'failed') status.textContent = failureText(run);
        }
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

  captureClick('#start-workbench', () => {
    const value = input.value.trim();
    if (!value) return;
    if (activeStage === 'topic' && !brief) {
      brief = value; submit(value, 'topic');
    } else runStage(activeStage, value);
  });
  captureClick('[data-workbench-stage]', button => selectStage(button.dataset.workbenchStage));
  captureClick('[data-topic-choice]', button => {
    const topics = stageArtifact('topic')?.content_json?.topics || [];
    const choice = topics[Number(button.dataset.topicChoice)];
    selectedTopic = String(typeof choice === 'string' ? choice : choice?.title || '').trim();
    if (!selectedTopic) return;
    localStorage.setItem(`universe.conversation.topic.${conversation.id}`, selectedTopic);
    renderStage();
  });
  captureClick('#workbench-stage-next', () => {
    const index = stages.findIndex(item => item.id === activeStage);
    const target = isStale(activeStage) || !stageArtifact(activeStage)
      ? activeStage : stages[index + 1]?.id;
    if (target) runStage(target);
  });
  captureClick('#workbench-stage-rerun', () => runStage(activeStage));
  captureClick('#workbench-view-toggle', () => setOutputOpen(!outputOpen));
  captureClick('#new-workbench-chat', () => {
    closeEvents(); conversation = null; activeRun = null; renderedEventIds = new Set();
    localStorage.removeItem(keyConversation); localStorage.removeItem(keyRun);
    activeStage = 'topic'; selectedTopic = ''; brief = ''; allArtifacts = [];
    submitting = false; setBusy(false); input.value = ''; renderMessages([]); renderArtifacts([]); status.textContent = '等待你的想法';
    syncSkillPicker();
  });
  captureClick('#recent-workbench-chats', () => toggleConversationHistory());
  captureClick('[data-conversation-id]', button => openConversation(button.dataset.conversationId));
  captureClick('#cancel-workbench', async () => {
    if (!activeRun) return;
    try { await api(`/api/runs/${encodeURIComponent(activeRun)}/cancel`, { method: 'POST' }); }
    catch (error) { appendNotice(error.message); }
  });
  captureClick('#workbench-regenerate-topics', () => {
    input.value = '请重新给我 10 个更具体的选题方向，并说明每个方向为什么值得写。'; input.focus();
  });
  captureClick('.mode-option', button => {
    if (conversation || activeRun) return;
    selectedMode = button.dataset.mode === 'auto' ? 'auto' : 'manual';
    modeButtons.forEach(item => item.classList.toggle('active', item === button));
    syncSkillPicker();
  });
  skillPicker.addEventListener('change', () => {
    if (conversation || activeRun) { skillPicker.value = selectedSkill; return; }
    selectedSkill = skillPicker.value;
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
    event.preventDefault(); event.stopImmediatePropagation();
    if (activeStage === 'topic' && !brief) { brief = input.value.trim(); submit(brief, 'topic'); }
    else runStage(activeStage, input.value.trim());
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
  async function loadSkills() {
    try {
      const catalog = (await api('/api/skills')).skills || [];
      for (const skill of catalog.filter(item => item.id.startsWith('easel_'))) {
        const option = document.createElement('option');
        option.value = skill.id;
        option.textContent = skill.name;
        skillPicker.append(option);
      }
      syncSkillPicker();
    } catch { /* The existing WeChat Skill remains available. */ }
  }

  function syncSkillPicker() {
    skillPicker.value = selectedSkill;
    if (!skillPicker.value) skillPicker.value = 'wechat_writer';
    skillPicker.disabled = Boolean(conversation || activeRun || selectedMode === 'auto');
    skillPicker.parentElement.hidden = selectedMode === 'auto';
  }

  syncSkillPicker();
  loadSkills();
  restore();
})();
