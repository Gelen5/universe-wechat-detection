(() => {
  'use strict';

  const root = document.querySelector('#workbench.normalized-conversation');
  if (!root) return;
  const thread = root.querySelector('#workbench-chat-thread');
  const input = root.querySelector('#workbench-topic');
  try {
    const homeDraft = sessionStorage.getItem('universe.homeDraft');
    if (homeDraft) {
      input.value = homeDraft;
      sessionStorage.removeItem('universe.homeDraft');
    }
  } catch { /* private mode */ }
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
  const taskButton = document.createElement('button');
  taskButton.type = 'button'; taskButton.id = 'active-workbench-runs';
  taskButton.className = 'new-chat-button pd-ghost'; taskButton.textContent = '任务';
  taskButton.setAttribute('aria-expanded', 'false'); taskButton.setAttribute('aria-controls', 'workbench-task-list');
  const headerActions = root.querySelector('.pd-pageact') || document.createElement('nav');
  headerActions.className = 'pd-pageact runtime-tools'; headerActions.setAttribute('aria-label', '创作操作');
  root.querySelector('.studio-heading').append(headerActions);
  headerActions.append(taskButton);
  const taskList = document.createElement('section');
  taskList.id = 'workbench-task-list'; taskList.className = 'conversation-history-popover task-list';
  taskList.hidden = true; taskList.setAttribute('aria-label', '我的活动任务');
  root.append(taskList);
  progress.setAttribute('aria-hidden', 'true');
  const stageNav = root.querySelector('#workbench-stage-nav');
  const stageTitle = root.querySelector('#workbench-stage-title');
  const stageHint = root.querySelector('#workbench-stage-hint');
  const stageKicker = root.querySelector('#workbench-stage-kicker');
  const stageNext = root.querySelector('#workbench-stage-next');
  const stageRerun = root.querySelector('#workbench-stage-rerun');
  const stageChoices = root.querySelector('#workbench-stage-choices');
  const htmlPreview = root.querySelector('#workbench-html-preview');
  htmlPreview.addEventListener('load', () => {
    const doc = htmlPreview.contentDocument;
    if (!doc) return;
    const resize = () => htmlPreview.style.setProperty('height', Math.max(360, doc.documentElement.scrollHeight) + 'px', 'important');
    resize();
    doc.querySelectorAll('img').forEach(image => image.addEventListener('load', resize, {once:true}));
  });
  const keyConversation = 'universe.conversation.workbench';
  const keyRun = 'universe.conversation.activeRun';
  const keyPending = 'universe.conversation.pendingRequest';
  const stageKey = id => `universe.conversation.stage.${id}`;
  const directionKey = id => `universe.conversation.direction.${id}`;
  const stages = [
    { id: 'topic', label: '选题', hint: '输入主题，选择一个值得写的方向。' },
    { id: 'outline', label: '大纲', hint: '确认文章结构；可以直接修改大纲。' },
    { id: 'writing', label: '写作', hint: '根据确认的大纲生成正文。' },
    { id: 'deai', label: '去 AI', hint: '调整结构和表达，使文章更自然；保护事实和原意。' },
    { id: 'typeset', label: '排版', hint: '用最新正文生成公众号 HTML 预览。' },
  ];
  const stageLabel = id => stages.find(item => item.id === id)?.label || '当前阶段';
  // 没有附加文字时，用一句自然语言驱动某个阶段（真正的阶段指令由后端生成）。
  const defaultPrompt = {
    topic: '给我一些可以写的选题',
    outline: '按这个选题生成大纲',
    writing: '开始写正文',
    deai: '做一次去 AI 和事实复核',
    typeset: '把最新正文排版成公众号 HTML',
  };
  // 每一步要等 1-4 分钟，必须让用户看见"现在在干什么、等了多久"。
  const STAGE_STEPS = {
    topic: [['submit', '提交任务'], ['intent', '理解要求'], ['hotspots', '抓取热点'],
            ['search', '搜索参考'], ['generating', '生成方向'], ['saving', '保存结果']],
    outline: [['submit', '提交任务'], ['intent', '理解要求'], ['generating', '生成大纲'],
              ['saving', '保存结果']],
    writing: [['submit', '提交任务'], ['intent', '理解要求'], ['generating', '撰写正文'],
              ['saving', '保存结果']],
    deai: [['submit', '提交任务'], ['intent', '理解要求'], ['generating', '复核与改写'],
           ['saving', '保存结果']],
    typeset: [['submit', '提交任务'], ['intent', '理解要求'], ['generating', '生成排版'],
              ['saving', '保存结果']],
  };
  let progressStage = 'topic';
  let progressSteps = [];
  let stepState = {};
  let progressNote = '';
  let progressStartedAt = 0;
  let progressTimer = null;
  let runtimeState = null;

  function runtimeTitle() { return window.RunPresentation.title(runtimeState, stageLabel(progressStage)); }

  function applyRuntime(action) {
    if (!runtimeState) return;
    const previous = runtimeState;
    runtimeState = window.RunPresentation.reduce(runtimeState, action);
    if (runtimeState === previous) return;
    root.dataset.runPhase = runtimeState.phase;
    if (runtimeState.stage !== previous.stage && stages.some(item => item.id === runtimeState.stage)) {
      selectStage(runtimeState.stage);
      if (!progress.hidden) beginProgress(runtimeState.stage);
    }
    if (runtimeState.createdAt) progressStartedAt = runtimeState.createdAt;
    tickProgress(); renderStage(); renderActionCard();
  }

  function formatElapsed(ms) {
    const total = Math.max(0, Math.round(ms / 1000));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
  }

  function tickProgress() {
    if (!progressSteps.length) return;
    const done = progressSteps.filter(step => ['done', 'skipped'].includes(stepState[step.key])).length;
    const active = progressSteps.find(step => stepState[step.key] === 'active');
    const failed = progressSteps.find(step => stepState[step.key] === 'failed');
    const pct = Math.round((done / progressSteps.length) * 100);
    if (progress && !progress.hidden) {
      progressTitle.textContent = runtimeTitle();
      progressBar.style.width = `${Math.max(6, Math.min(100, pct))}%`;
      const elapsed = `已等待 ${formatElapsed(Date.now() - progressStartedAt)}`;
    const state = failed ? '这一步失败了' : (progressNote || (active ? `${active.label}…` : '即将完成'));
      progressDetail.textContent = `${state} · ${elapsed}`;
    }
    const elapsedEl = thread.querySelector('#chat-elapsed');
    if (elapsedEl) elapsedEl.textContent = `已等待 ${formatElapsed(Date.now() - progressStartedAt)}`;
  }

  function beginProgress(stage) {
    progressStage = stages.some(item => item.id === stage) ? stage : activeStage;
    const defs = STAGE_STEPS[progressStage] || STAGE_STEPS.topic;
    progressSteps = defs.map(([key, label]) => ({ key, label }));
    stepState = Object.fromEntries(progressSteps.map(step => [step.key, 'pending']));
    stepState[progressSteps[0].key] = 'active';
    progressNote = '';
    progressStartedAt = runtimeState?.createdAt || Date.now();
    clearInterval(progressTimer);
    progressTimer = setInterval(tickProgress, 1000);
    tickProgress();
  }

  function endProgress() {
    clearInterval(progressTimer);
    progressTimer = null;
    progressSteps = [];
    stepState = {};
    progressNote = '';
  }

  function setStep(key, state, detail = '') {
    if (!progressSteps.length || !(key in stepState)) return;
    stepState[key] = state;
    if (detail) progressNote = detail;
    tickProgress();
    if (progress && !progress.hidden) renderActionCard();
  }

  function activateNextStep(after = ['submit', 'intent']) {
    const next = progressSteps.find(step => !after.includes(step.key)
      && ['pending', 'active'].includes(stepState[step.key]));
    if (next) setStep(next.key, 'active');
  }

  let accountEpoch = 0;
  let accountId;
  let navigationSequence = 0;
  let taskRows = [], taskCursor = null, taskReadSequence = 0;
  let conversation = null;
  let activeRun = null;
  let source = null;
  let runStatusTimer = null;
  let selectedMode = 'manual';
  let selectedSkill = 'wechat_writer';
  let renderedEventIds = new Set();
  let currentArtifact = null;
  let outputOpen = false;
  let editableArtifacts = [];
  let artifactIndex = -1;
  let saveTimer = null;
  let editSequence = 0;
  let pendingEdit = null;
  let savingEdits = 0;
  let deferredRefresh = false;
  let saving = Promise.resolve();
  let pendingSubmission = null;
  let pendingPersisted = true;
  const savedHeads = new Map();

  function retainSubmission(record) {
    pendingSubmission = record;
    pendingPersisted = true;
    // Tab-local draft state, cleared on identity changes. Never store tokens or
    // provider credentials. The server independently checks ownership/replays.
    try {
      if (record) sessionStorage.setItem(keyPending, JSON.stringify(record));
      else sessionStorage.removeItem(keyPending);
    } catch { pendingPersisted = !record; }
  }

  async function findPendingRun(record) {
    try {
      return (await api(`/api/conversations/${encodeURIComponent(record.conversationId)}/requests/${encodeURIComponent(record.key)}`)).run || null;
    } catch (error) {
      if (error.status === 404) return null;
      throw error;
    }
  }

  async function recoverPendingSubmission() {
    let record;
    try { record = JSON.parse(sessionStorage.getItem(keyPending) || 'null'); } catch { return; }
    if (!record || record.conversationId !== conversation?.id || !record.key || !record.contentJson) return;
    retainSubmission(record);
    try {
      const run = await findPendingRun(record);
      if (!run) {
        input.value = record.content;
        status.textContent = '上次提交尚未确认；重发原指令会沿用同一请求';
        return;
      }
      retainSubmission(null);
      if (run.stage) selectStage(run.stage);
      if (['queued', 'running'].includes(run.status)) watchRun(run.id, run);
      else {
        localStorage.removeItem(keyRun);
        await refresh();
        status.textContent = run.status === 'failed' ? failureText(run) : '已找回上次任务及结果';
      }
    } catch (error) { appendNotice(`正在保留上次提交记录：${error.message}`); }
  }

  function showSaveConflict() {
    let controls = root.querySelector('.draft-recovery');
    if (!controls) {
      controls = document.createElement('span');
      controls.className = 'draft-recovery';
      const copy = document.createElement('button');
      copy.type = 'button'; copy.textContent = '复制未保存正文';
      copy.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(editor.value); saveState.textContent = '当前修改已复制；读取最新版本后可合并'; }
        catch { saveState.textContent = '浏览器未允许复制，请在编辑框内全选并复制后再读取最新版本'; }
      });
      const reload = document.createElement('button');
      reload.type = 'button'; reload.textContent = '读取最新版本';
      reload.addEventListener('click', async () => {
        if (savingEdits || !window.confirm('将用最新版本替换编辑框。请先复制保留当前修改，确认继续？')) return;
        clearTimeout(saveTimer); pendingEdit = null; editSequence++; saving = Promise.resolve();
        savedHeads.clear(); controls.hidden = true;
        try { await refresh(); } catch (error) { appendNotice(error.message); }
      });
      controls.append(copy, reload); saveState.after(controls);
    }
    controls.hidden = false;
  }

  async function flushEdits() {
    const epoch = accountEpoch;
    clearTimeout(saveTimer);
    if (pendingEdit) {
      const edit = pendingEdit;
      pendingEdit = null;
      saving = saving.catch(() => {}).then(() => saveArtifactEdit(...edit));
    }
    await saving;
    if (epoch !== accountEpoch) throw new Error('账号已切换，请重新操作');
  }
  // Lock before the async conversation creation/request starts. Waiting for
  // the API response here would allow rapid clicks to create duplicate runs.
  let submitting = false;
  let activeStage = 'topic';
  let allArtifacts = [];
  let artifactTotal = 0;
  let artifactCursor = null;
  let selectedTopic = '';
  let direction = '';
  let lastMessages = [];

  const escapeHtml = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  }[char]));

  // ---- 选题工作区 -------------------------------------------------------
  // 方向只在一个地方完整展示：左侧作品区。对话流里不再重复整份清单，
  // 只保留一句状态说明和下一步动作，避免同一批标题出现两遍。
  function topicMeta(choice) {
    return choice && typeof choice === 'object' ? choice : { title: String(choice ?? '') };
  }

  function topicTitle(choice) {
    return String(topicMeta(choice).title || '').trim();
  }

  function safeTopicUrl(value) {
    const url = String(value || '').trim();
    return /^https?:\/\//i.test(url) ? escapeHtml(url) : '';
  }

  function topicEvidenceHtml(item) {
    const evidence = item?.content_json?.evidence;
    if (!evidence || typeof evidence !== 'object') return '';
    const sources = (Array.isArray(evidence.search_sources) ? evidence.search_sources : [])
      .filter(source => source && typeof source === 'object').slice(0, 6);
    const hotspots = (Array.isArray(evidence.platform_hotspots) ? evidence.platform_hotspots : [])
      .filter(source => source && typeof source === 'object').slice(0, 6);
    if (!sources.length && !hotspots.length) return '';
    const checked = String(evidence.checked_at || '').trim();
    const sourcesHtml = sources.map(source => {
      const url = safeTopicUrl(source.url);
      const title = escapeHtml(source.title || '未命名线索');
      const meta = [source.provider, source.published_at].filter(Boolean).map(escapeHtml).join(' · ');
      return `<li>${url ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${title}</a>` : `<span>${title}</span>`}${meta ? `<small>${meta}</small>` : ''}</li>`;
    }).join('');
    const hotspotsHtml = hotspots.map(source => {
      const platforms = Array.isArray(source.platforms) ? source.platforms.join(' / ') : '';
      return `<li><span>${escapeHtml(source.title || '')}</span>${platforms ? `<small>${escapeHtml(platforms)}</small>` : ''}</li>`;
    }).join('');
    return `<details class="topic-evidence">
      <summary>检索依据 <span>${sources.length + hotspots.length} 条线索${checked ? ` · ${escapeHtml(checked)}` : ''}</span></summary>
      <div class="topic-evidence-body">
        ${sourcesHtml ? `<section><h4>搜索线索</h4><ul>${sourcesHtml}</ul><p>线索摘要，未核实原文。</p></section>` : ''}
        ${hotspotsHtml ? `<section><h4>平台榜单</h4><ul>${hotspotsHtml}</ul><p>采集时间不是内容发布时间。</p></section>` : ''}
      </div>
    </details>`;
  }

  function topicBoardHtml(item, topics) {
    const normalized = (Array.isArray(topics) ? topics : []).map(topicMeta);
    if (!normalized.length) return '';
    const scored = normalized.map((topic, index) => ({
      index,
      score: (Number(topic.fan_score) || 0) * 0.7 + (Number(topic.heat) || 0) * 3,
    }));
    const hasScore = normalized.some(topic => Number(topic.heat) > 0 || Number(topic.fan_score) > 0);
    const recommended = normalized.length > 1 && hasScore
      ? scored.slice().sort((a, b) => b.score - a.score)[0].index : -1;
    const cards = normalized.map((topic, index) => {
      const name = String(topic.title || '').trim();
      if (!name) return '';
      const selected = name === selectedTopic;
      const type = String(topic.type || '方向').trim();
      const heat = Math.max(0, Math.min(10, Number(topic.heat) || 0));
      const hasHeat = topic.heat !== null && topic.heat !== undefined && topic.heat !== '' && Number.isFinite(Number(topic.heat));
      const hasFan = topic.fan_score !== null && topic.fan_score !== undefined && topic.fan_score !== '' && Number.isFinite(Number(topic.fan_score));
      const fan = Math.max(0, Math.min(100, Number(topic.fan_score) || 0));
      const hasMetrics = hasHeat || hasFan || ['低', '中', '高'].includes(String(topic.competition));
      const competition = ['低', '中', '高'].includes(String(topic.competition))
        ? String(topic.competition) : '未评估';
      return `<button type="button" class="topic-row${selected ? ' is-selected' : ''}"
          data-topic-choice="${index}" aria-pressed="${selected}">
        <span class="topic-row-index">${String(index + 1).padStart(2, '0')}</span>
        <span class="topic-row-main">
          <span class="topic-row-heading">
            <strong class="topic-row-title">${escapeHtml(name)}</strong>
          </span>
          ${topic.reason ? `<span class="topic-row-reason">${escapeHtml(topic.reason)}</span>` : ''}
          <span class="topic-row-badges">
            <span class="topic-row-type">${escapeHtml(type)}</span>
            ${index === recommended ? '<span class="topic-row-pick" title="按模型估计的热度与涨粉潜力综合排序">推荐</span>' : ''}
          </span>
          ${hasMetrics ? `<span class="topic-row-meta">
            <span class="topic-signal" title="模型估计热度，不是平台真实数据">
              <span class="topic-signal-label">热度</span>
              <b>${hasHeat ? heat : "—"}<small>${hasHeat ? " / 10" : ""}</small></b>
              <span class="topic-meter" aria-hidden="true"><i style="width:${hasHeat ? heat * 10 : 0}%"></i></span>
            </span>
            <span class="topic-signal" title="模型估计涨粉潜力，不是平台真实数据">
              <span class="topic-signal-label">涨粉潜力</span>
              <b>${hasFan ? fan : "—"}<small>${hasFan ? " / 100" : ""}</small></b>
              <span class="topic-meter" aria-hidden="true"><i style="width:${hasFan ? fan : 0}%"></i></span>
            </span>
            <span class="topic-row-competition" data-level="${escapeHtml(competition)}" title="模型估计竞争度，不是平台真实数据"><span class="topic-signal-label">竞争度</span><b>${escapeHtml(competition)}</b></span>
          </span>` : ''}
        </span>
        <span class="topic-row-state" aria-hidden="true">${selected ? '✓' : '›'}</span>
      </button>`;
    }).join('');
    return `<div class="topic-board">
      <header class="topic-board-head">
        <div>
          <strong>选一个能写下去的方向</strong>
        </div>
      </header>
      <div class="topic-row-list">${cards}</div>
      ${topicEvidenceHtml(item)}
    </div>`;
  }

  async function api(path, options = {}) {
    const epoch = accountEpoch;
    let response;
    try { response = await fetch(path, options); }
    catch (error) {
      throw new Error(error.name === 'TimeoutError' ? '请求响应较慢，请稍后确认结果' : '网络连接暂时中断，请检查网络后重试');
    }
    await window.AccountLifecycle?.checkResponse(response);
    const type = response.headers.get('content-type') || '';
    if (!type.includes('application/json')) {
      const error = new Error(`服务响应异常（${response.status}），请稍后确认结果`);
      error.status = response.ok ? 502 : response.status;
      throw error;
    }
    let data;
    try { data = await response.json(); }
    catch { throw new Error('响应未完整接收，请稍后重试'); }
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('响应格式异常，请稍后确认结果');
    if (epoch !== accountEpoch) throw new Error('账号已切换，已忽略之前的响应');
    window.PointsNotice?.fromResponse(response, data);
    if (!response.ok) {
      const error = new Error(data.detail || `请求失败（${response.status}）`);
      error.status = response.status;
      throw error;
    }
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
      if (!progressSteps.length) beginProgress(activeStage);
      progressTitle.textContent = label || `正在执行：${stageLabel(progressStage)}`;
      tickProgress();
    } else {
      endProgress();
    }
    renderStage();
    renderActionCard();
  }

  function messageMeta(message) {
    const meta = message.content_json;
    return meta && typeof meta === 'object' ? meta : {};
  }

  function failureCard(message, meta) {
    const stage = meta.stage || activeStage;
    const retry = meta.retryable === false ? '' : `
      <div class="chat-failure-actions">
        <button type="button" class="chat-action-primary" data-retry-stage="${escapeHtml(stage)}">重试这一步</button>
        <button type="button" class="chat-action-ghost" data-workbench-view-toggle>查看作品</button>
      </div>`;
    const technical = meta.technical
      ? `<details class="chat-failure-tech"><summary>技术信息</summary><code>${escapeHtml(meta.technical)}</code></details>`
      : '';
    return `<article class="chat-message from-ai is-failure" data-failure-stage="${escapeHtml(stage)}">
      <span>执行失败</span>
      <div class="chat-failure"><p>${escapeHtml(message.content)}</p>${technical}${retry}</div>
    </article>`;
  }

  function renderMessage(message) {
    const meta = messageMeta(message);
    if (meta.kind === 'run_failed') return failureCard(message, meta);
    const role = message.role === 'user' ? '你' : message.role === 'tool' ? '工具' : 'AI 共创助手';
    const kind = meta.kind === 'stage_note' ? ' is-note' : '';
    return `<article class="chat-message ${message.role === 'user' ? 'from-user' : 'from-ai'}${kind}">
      <span>${role}</span>
      <p>${escapeHtml(message.content)}</p>
    </article>`;
  }

  function renderMessages(messages) {
    lastMessages = messages;
    // 方向只认显式字段，不再拿"第一条消息"猜：否则一句"继续"会被永久当成选题方向。
    const latestTopic = [...messages].reverse().find(message => message.role === 'user' &&
      messageMeta(message).workflow_stage === 'topic' &&
      String(messageMeta(message).topic_direction || '').trim());
    if (!direction && latestTopic) direction = String(messageMeta(latestTopic).topic_direction).trim();
    thread.innerHTML = messages.length ? messages.map(renderMessage).join('') : `
      <article class="chat-message from-ai"><span>创作助手</span>
        <p>像聊天一样告诉我你想写什么，我从选题开始带你走到排版。每一步都会出现在这里，失败也能直接重试。</p>
      </article>`;
    renderActionCard();
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

  const failureHints = {
    provider_access: '文字 API Key 未允许服务器 IP 访问，请联系管理员检查白名单；本轮积分已退还',
    provider_balance: '文本 API 额度不足，请联系管理员充值；本轮积分已退还',
    provider_connection: '模型服务暂时断开，稍后重试即可；本轮积分已退还',
    provider: '模型服务出错了，稍后重试即可；本轮积分已退还',
    layout_validation: '排版自动修复后仍未通过完整性或兼容检查，原稿已保留；本轮积分已退还',
    layout_image: '图片无法安全复制，请检查图片格式和大小；本轮积分已退还',
    skill_missing: '服务端缺少公众号 Skill 文件，请联系管理员；本轮积分已退还',
    stage_tool_missing: '当前版本缺少这个阶段的执行工具，请换个阶段；本轮积分已退还',
    topic_source: '抓取热点超时或被网络拦截，重试即可；本轮积分已退还',
    topic_schema: '模型返回的选题结构不合格，重试或把方向写具体一点；本轮积分已退还',
    timeout: '这一步超时了，可以拆小一点再试；本轮积分已退还',
    queue: '任务暂时无法进入队列，稍后重试；积分已退还',
  };

  function failureText(payload = {}) {
    const error = String(payload.error_message || '').toLowerCase();
    const kind = payload.error_code || payload.error_kind || (
      /ip 不在令牌允许访问|ip is not allowed/.test(error) ? 'provider_access' :
      /额度不足|余额不足|insufficient balance|insufficient_quota/.test(error) ? 'provider_balance' :
      /provider connection failed|remote end closed|connection reset/.test(error) ? 'provider_connection' : '');
    return failureHints[kind] || '本轮执行失败，已按规则退还积分';
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
    if (value) {
      window.requestAnimationFrame(() => {
        const canvas = root.querySelector('.article-canvas');
        if (canvas) canvas.scrollTop = 0;
        window.scrollTo(0, 0);
      });
    }
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
    if (stage === 'typeset' && window.PublisherCopy.isStale(stageArtifact(stage), latestOf('article'))) return true;
    const previous = stageArtifact(stages[index - 1].id);
    return Boolean(previous && previous.updated_at > stageArtifact(stage).updated_at);
  }

  function selectStage(stage) {
    if (!stages.some(item => item.id === stage)) return;
    activeStage = stage;
    if (conversation) localStorage.setItem(stageKey(conversation.id), stage);
    renderStage();
    if (window.matchMedia('(max-width: 1100px)').matches && stageArtifact(stage)) setOutputOpen(true);
  }

  function renderStage() {
    const index = stages.findIndex(item => item.id === activeStage);
    const stage = stages[index] || stages[0];
    const item = stageArtifact(stage.id);
    const stale = isStale(stage.id);
    stageKicker.textContent = `${String(index + 1).padStart(2, '0')} / 05`;
    stageTitle.textContent = stage.label;
    stageHint.textContent = stale ? '上游作品已修改，请更新本阶段结果。' : stage.hint;
    // 输入框永远说明"现在这一步要什么"，而不是让用户猜。
    const placeholders = {
      topic: '想写什么方向？写给谁、解决什么问题，一句话就够',
      outline: '对结构有什么要求？几段、先讲什么后讲什么',
      writing: '篇幅、语气、给谁看；有素材也可以贴在这里',
      deai: '复核重点：事实、口吻、还是某一段太长',
      typeset: '排版风格，例如极简白 / 科技卡片绿 / 极简优雅',
    };
    if (placeholders[stage.id]) input.placeholder = placeholders[stage.id];
    stageNav.innerHTML = stages.map((entry, position) => {
      const done = Boolean(stageArtifact(entry.id));
      const runningLabel = ({saving: '保存中', submitting: '提交中', queued: '排队中', reconnecting: '重连中', cancelling: '取消中'})[runtimeState?.phase] || (done ? '更新中' : '执行中');
      const state = send.disabled && entry.id === progressStage ? runningLabel : isStale(entry.id) ? '需更新' : done ? '已完成' : position === index ? '当前阶段' : '待开始';
      return `<button type="button" data-workbench-stage="${entry.id}" ${position === index ? 'aria-current="step"' : ''}>
        <span>${String(position + 1).padStart(2, '0')} ${entry.label}</span><small>${state}</small></button>`;
    }).join('');
    const editorWrap = editor.closest('.editor-wrap');
    const hasText = item && item.type !== 'html' && stage.id !== 'topic';
    editorWrap.hidden = !hasText;
    htmlPreview.hidden = stage.id !== 'typeset' || !item;
    stageChoices.innerHTML = '';
    if (stage.id === 'typeset' && item) {
      currentArtifact = item;
      try { htmlPreview.srcdoc = window.PublisherCopy.preview(item); }
      catch (error) { htmlPreview.srcdoc = '<p style="font:16px/1.8 system-ui;padding:24px">' + escapeHtml(error.message) + '</p>'; }
    }
    if (stage.id === 'topic' && item) {
      const topics = item.content_json?.topics || [];
      if (Array.isArray(topics) && topics.length) {
        stageChoices.innerHTML = topicBoardHtml(item, topics);
      }
    }
    if (stage.id === 'deai' && item) {
      const revised = latestOf('article', candidate => candidate.run_id === item.run_id);
      showArtifact(revised || item);
      const review = item.content_json?.review || item.content_json;
      if (review && review.gate) {
        stageChoices.innerHTML = `<p role="status">${escapeHtml(review.summary || (review.changed ? '已生成修订稿' : '本次复核未修改正文，请查看报告'))}</p><details><summary>查看复核报告</summary><pre>${escapeHtml(JSON.stringify(review, null, 2))}</pre></details>`;
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
      (index > 0 && !item && !stageArtifact(stages[index - 1].id)));
    viewToggle.hidden = !allArtifacts.length;
    resultMeta.textContent = item ? `${artifactKind(item)} · V${item.version}` : '当前阶段尚无作品';
  }

  function firstMissingStage() {
    // 用户可以直接给出主题、跳过候选选题，所以「没有选题作品」本身不代表链路断了。
    // 只要后续阶段已经有作品，下一步就接在后面，而不是要求回头重新选题。
    const completed = stages.map((stage, index) => stageArtifact(stage.id) ? index : -1);
    const last = Math.max(-1, ...completed);
    return stages[last + 1]?.id || null;
  }

  function latestFailure() {
    const last = [...lastMessages].reverse().find(message => message.role === 'assistant');
    return last && messageMeta(last).kind === 'run_failed' ? last : null;
  }

  // 阶段不再由前端按关键词猜：一句话交给后端的意图调度（server/agent/intent.py），
  // 由模型结合当前进度判断；按钮/标签点击才是显式指定阶段。
  function renderActionCard() {
    const follow = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 100;
    thread.querySelector('#workbench-action-card')?.remove();
    const card = document.createElement('article');
    card.id = 'workbench-action-card';
    card.className = 'chat-action-card';
    const busy = progress && !progress.hidden;
    const failure = latestFailure();
    const topicItem = stageArtifact('topic');
    const next = firstMissingStage();
    let html = '';
    if (busy) {
      const steps = (progressSteps.length ? progressSteps : STAGE_STEPS.topic.map(([key, label]) => ({ key, label })))
        .map(step => `<li data-state="${stepState[step.key] || 'pending'}">${escapeHtml(step.label)}</li>`)
        .join('');
      const elapsed = formatElapsed(Date.now() - (progressStartedAt || Date.now()));
      const phase = runtimeState?.phase;
      const explanation = phase === 'queued' ? '等待执行资源；尚未开始生成正文。'
        : phase === 'reconnecting' ? '暂时无法获取最新进度；任务可能仍在执行，正在核对状态。'
        : phase === 'cancelling' ? (runtimeState?.cancelUnconfirmed ? '尚未确认服务端是否停止，可再次确认取消。' : '已请求停止，正在确认结果。确认前不会创建新任务。')
        : phase === 'saving' ? '先保存当前修改，保存成功后才会提交任务。'
        : phase === 'submitting' ? '正在确认请求是否已接收，请勿重复提交。'
        : '离开后，可在「任务」找回进度。';
      html = `<strong role="status" aria-live="polite">${escapeHtml(runtimeTitle())}</strong>
        <ol class="chat-steps">${steps}</ol>
        <p><span id="chat-elapsed">已等待 ${elapsed}</span>${progressNote ? ` · ${escapeHtml(progressNote)}` : ''}</p>
        <p class="chat-steps-hint">${explanation}</p>
        ${activeRun ? `<button type="button" data-cancel-run ${runtimeState?.cancelRequested && !runtimeState.cancelUnconfirmed ? 'disabled' : ''}>${runtimeState?.cancelUnconfirmed ? '再次确认取消' : runtimeState?.cancelRequested ? '正在确认取消' : '取消任务'}</button>` : ''}`;
    } else if (pendingSubmission && !activeRun) {
      html = '<strong>上次提交待确认</strong><p>记录已保留。先确认原请求，再开始新任务。</p><button type="button" data-resume-pending>继续确认上次提交</button>';
    } else if (runtimeState?.status === 'failed' && !failure) {
      html = `<strong>本轮未完成</strong><p>已有作品保留。请查看上方错误说明和账户积分记录。</p><button type="button" data-retry-stage="${escapeHtml(runtimeState.stage || activeStage)}">重试本阶段</button>`;
    } else if (['cancelled', 'waiting_input'].includes(runtimeState?.status)) {
      html = `<strong>${escapeHtml(runtimeTitle())}</strong><p>${runtimeState.status === 'cancelled'
        ? '任务已停止，已有作品保留。积分状态可在账户账单中查看。'
        : '请在输入框补充要求后继续，已有作品保留。'}</p>`;
    } else if (failure) {
      const meta = messageMeta(failure);
      const stage = meta.stage || activeStage;
      html = `<strong>${escapeHtml(stageLabel(stage))}这一步没有完成</strong>
        <p>原因和积分状态见上方卡片。重试只重跑这一步，已完成的阶段不会丢。</p>
        <div class="chat-action-row">
          <button type="button" class="chat-action-primary" data-retry-stage="${escapeHtml(stage)}">重试：${escapeHtml(stageLabel(stage))}</button>
        </div>`;
    } else if (!allArtifacts.some(item => ['topic', 'outline', 'article', 'report', 'html'].includes(item.type))) {
      // 真正的起点：既没有选题作品，也没有大纲。
      html = `<strong>先告诉我你想写什么</strong>
        <p>一句话就够，例如「写一篇给 30 岁职场人的 AI 工具实测」。</p>`;
    } else if (topicItem && !selectedTopic && next === 'outline') {
      // 只有还没进入大纲时才要求选方向；已经有大纲说明方向已经落地过，
      // 再要求选一次会把已经推进的链路挡回去。
      const topics = (topicItem.content_json?.topics || []).filter(choice => topicTitle(choice));
      html = `<strong>${topics.length ? `${topics.length} 个方向已就绪` : '还没有可用方向'}</strong>
        <p>${topics.length
          ? `选题已准备好。查看选题并选择一个方向，我接着写大纲。`
          : '这次没有返回可用方向，可以重新生成。'}</p>
        <div class="chat-action-row">
          ${topics.length ? '<button type="button" class="chat-action-primary" data-focus-topics>查看选题</button>' : ''}
          <button type="button" class="${topics.length ? 'chat-action-ghost' : 'chat-action-primary'}" data-retry-stage="topic">${topics.length ? '换一批' : '重新生成选题'}</button>
        </div>`;
    } else if (next) {
      // 卡片跟着作品链走：用户直接给主题时没有选题作品，也不能因此停在「大纲已就绪」。
      const direction = topicItem && selectedTopic
        ? `<p class="chat-selection-label">已选方向</p>
        <p class="chat-selected-topic">${escapeHtml(selectedTopic)}</p>
        <p class="chat-action-note">已完成的阶段会保留，可随时返回修改。</p>`
        : `<p class="chat-action-note">已完成的阶段会保留，可随时返回修改，或回到选题换个方向。</p>`;
      // 没有正文时不该出现「直接排版」：排版节点没有可排的内容，点了只会报错。
      const directTypeset = next !== 'typeset' && stageArtifact('writing')
        ? '<button type="button" class="chat-action-ghost" data-next-stage="typeset">直接排版</button>'
        : '';
      html = `<strong>下一步：${escapeHtml(stageLabel(next))}</strong>
        ${direction}
        <div class="chat-action-row">
          <button type="button" class="chat-action-primary" data-next-stage="${next}">继续：${escapeHtml(stageLabel(next))}</button>
          ${directTypeset}
        </div>`;
    } else if (window.PublisherCopy.isStale(stageArtifact('typeset'), latestOf('article'))) {
      html = `<strong>正文已更新，排版需要更新</strong>
        <p>重新排版后才能复制最新正文；历史版本仍可查看。</p>
        <div class="chat-action-row">
          <button type="button" class="chat-action-primary" data-next-stage="typeset">重新排版</button>
          <button type="button" class="chat-action-ghost" data-workbench-view-toggle>查看作品</button>
        </div>`;
    } else {
      html = `<strong>这篇稿子已经排好版</strong>
        <p>复制到公众号后台即可。要改正文就点「查看作品」直接编辑，改动会自动保存成新版本；说「重新排版」可以再来一次。</p>
        <div class="chat-action-row">
          <button type="button" class="chat-action-primary" data-copy-html>复制排版</button>
          <button type="button" class="chat-action-ghost" data-workbench-view-toggle>查看作品</button>
        </div>`;
    }
    card.innerHTML = html;
    thread.append(card);
    if (follow) thread.scrollTop = thread.scrollHeight;
  }

  function showArtifact(item) {
    if (!item) return;
    // Busy/status rendering must never replace a dirty editor with the saved
    // body while its save is pending or has failed.
    if ((pendingEdit || savingEdits) && currentArtifact?.id === item.id
        && editor.value !== (currentArtifact.content || '')) return;
    currentArtifact = item;
    artifactIndex = editableArtifacts.findIndex(candidate => candidate.id === item.id);
    title.textContent = item.title || artifactKind(item);
    editor.value = item.content || '';
    editor.readOnly = item.type === 'image';
    versionLabel.textContent = `${artifactKind(item)} · V${item.version}`;
  }

  async function openArtifact(item) {
    await flushEdits();
    const conversationId = conversation?.id;
    if (item.content_loaded === false) {
      saveState.textContent = '正在读取历史正文…';
      item = (await api(`/api/artifacts/${encodeURIComponent(item.id)}`)).artifact;
      if (conversation?.id !== conversationId) return;
      allArtifacts = allArtifacts.map(row => row.id === item.id ? item : row);
      editableArtifacts = editableArtifacts.map(row => row.id === item.id ? item : row);
    }
    showArtifact(item);
    artifactList.querySelectorAll('[data-artifact-id]').forEach(button => {
      button.classList.toggle('current', button.dataset.artifactId === item.id);
    });
    htmlPreview.hidden = item.type !== 'html';
    editor.closest('.editor-wrap').hidden = ['html', 'image', 'topic'].includes(item.type);
    if (item.type === 'html') htmlPreview.srcdoc = window.PublisherCopy.preview(item);
    saveState.textContent = '已读取历史版本；编辑将保存为新版本';
  }

  function renderArtifacts(artifacts) {
    root.querySelector('.artifact-history').hidden = !artifacts.length;
    const ordered = [...artifacts].sort((a, b) =>
      String(a.updated_at || a.created_at || '').localeCompare(String(b.updated_at || b.created_at || '')));
    allArtifacts = ordered;
    for (const item of ordered) {
      const previous = savedHeads.get(item.type);
      if (!previous || item.version > previous.version) savedHeads.set(item.type, item);
    }
    editableArtifacts = ordered.filter(item => ['article', 'outline', 'markdown', 'html', 'report', 'topic'].includes(item.type));
    const current = editableArtifacts.at(-1) || ordered.at(-1);
    if (!current) {
      currentArtifact = null;
      images.hidden = true; images.replaceChildren();
      viewToggle.hidden = true;
      renderStage();
      title.textContent = '作品会在这里出现'; editor.value = '';
      editor.readOnly = true;
      saveState.textContent = '等待生成当前阶段作品';
      versionLabel.textContent = '尚无作品'; changeLabel.textContent = '生成后会保留历史版本';
      artifactList.innerHTML = '<p class="empty-artifact">当前对话还没有作品</p>';
      return;
    }
    const firstArtifact = !currentArtifact;
    if (firstArtifact && conversation && !localStorage.getItem(stageKey(conversation.id))) {
      const available = stages.filter(stage => stageArtifact(stage.id));
      activeStage = available.at(-1)?.id || 'topic';
    }
    showArtifact(current);
    viewToggle.hidden = false;
    if (firstArtifact) setOutputOpen(false);
    saveState.textContent = '已保存到当前对话';
    versionLabel.textContent = `${artifactKind(current)} · V${current.version}`;
    changeLabel.textContent = '每次修改都会保留历史版本';
    resultMeta.textContent = `${artifactKind(current)} · ${artifactTotal || ordered.length} 个版本`;
    artifactList.innerHTML = ordered.slice().reverse().map(item => `
      <button class="version-item${item.id === current.id ? ' current' : ''}" data-artifact-id="${escapeHtml(item.id)}" type="button">
        <strong>${escapeHtml(artifactKind(item))} V${item.version}</strong><span>${escapeHtml(item.title || '未命名作品')}</span>
      </button>`).join('') + (artifactCursor ? '<button type="button" data-more-artifacts>读取更早版本</button>' : '');
    artifactList.querySelector('[data-more-artifacts]')?.addEventListener('click', async event => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await flushEdits();
        const id = conversation?.id;
        const data = await api(`/api/conversations/${encodeURIComponent(id)}/artifacts?view=workspace&before=${encodeURIComponent(artifactCursor)}`);
        if (conversation?.id !== id) return;
        artifactCursor = data.next_cursor || null;
        const selected = currentArtifact;
        renderArtifacts([...new Map([...allArtifacts, ...data.artifacts].map(item => [item.id, item])).values()]);
        if (selected) await openArtifact(selected);
      } catch (error) { appendNotice(error.message); button.disabled = false; }
    });
    artifactList.querySelectorAll('[data-artifact-id]').forEach(button => button.addEventListener('click', () => {
      const item = ordered.find(candidate => candidate.id === button.dataset.artifactId);
      if (!item) return;
      openArtifact(item).catch(error => appendNotice(error.message));
    }));
    const imageArtifacts = ordered.filter(item => item.type === 'image' && item.storage_url);
    images.hidden = !imageArtifacts.length;
    images.innerHTML = imageArtifacts.length ? `<div class="image-grid">${imageArtifacts.map(item => `
      <a href="${escapeHtml(item.storage_url)}" target="_blank" rel="noopener"><img src="${escapeHtml(item.storage_url)}" alt="${escapeHtml(item.title || '生成图片')}"><span><strong>${escapeHtml(item.title || '生成图片')}</strong><small>V${item.version}</small></span></a>`).join('')}</div>` : '';
    renderStage();
    renderActionCard();
  }

  async function refresh() {
    if (!conversation) return;
    const conversationId = conversation.id;
    const epoch = accountEpoch;
    const sequence = editSequence;
    const [messages, artifacts] = await Promise.all([
      api(`/api/conversations/${encodeURIComponent(conversation.id)}/messages`),
      api(`/api/conversations/${encodeURIComponent(conversation.id)}/artifacts?view=workspace`),
    ]);
    if (!Array.isArray(messages.messages) || !Array.isArray(artifacts.artifacts)) throw new Error('作品读取未完成，已保留当前内容，请稍后重试');
    if (epoch !== accountEpoch || conversation?.id !== conversationId) return;
    if (pendingEdit || savingEdits || sequence !== editSequence) {
      deferredRefresh = true;
      return;
    }
    artifactTotal = artifacts.total || 0;
    artifactCursor = artifacts.next_cursor || null;
    renderMessages(messages.messages || []); renderArtifacts(artifacts.artifacts || []);
  }

  async function saveArtifactEdit(sequence, artifact, content) {
    const epoch = accountEpoch;
    savingEdits++;
    try {
      const data = await api(`/api/artifacts/${encodeURIComponent(artifact.id)}/versions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, expected_current_id: savedHeads.get(artifact.type)?.id || artifact.id }),
        signal: AbortSignal.timeout(15000),
      });
      if (!data.artifact?.id) throw new Error('保存结果未完整返回，当前修改仍保留在编辑框');
      if (epoch !== accountEpoch) return;
      savedHeads.set(artifact.type, data.artifact);
      if (sequence !== editSequence) { deferredRefresh = true; return; }
      currentArtifact = data.artifact;
      root.querySelector('.draft-recovery')?.setAttribute('hidden', '');
      artifactTotal++;
      saveState.textContent = '已保存新版本';
      renderArtifacts([...allArtifacts.filter(item => item.id !== data.artifact.id), data.artifact]);
    } catch (error) {
      if (sequence === editSequence) {
        pendingEdit = [sequence, artifact, content];
        saveState.textContent = `保存失败：${error.message}；请重试，尚未执行下一步`;
        if (error.status === 409) showSaveConflict();
      }
      throw error;
    } finally {
      if (epoch === accountEpoch) {
        savingEdits--;
        if (!savingEdits && !pendingEdit && deferredRefresh) {
          deferredRefresh = false;
          refresh().catch(error => appendNotice(error.message));
        }
      }
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
    rememberConversationUrl(conversation.id);
    return conversation;
  }

  async function openConversation(conversationId) {
    const navigation = ++navigationSequence;
    try { await flushEdits(); } catch (error) { appendNotice(error.message); return; }
    const next = (await api(`/api/conversations/${encodeURIComponent(conversationId)}`)).conversation;
    if (navigation !== navigationSequence) return;
    closeEvents(); activeRun = null; localStorage.removeItem(keyRun);
    runtimeState = null; root.removeAttribute('data-run-phase'); setBusy(false);
    savedHeads.clear();
    currentArtifact = null;
    conversation = next;
    activeStage = localStorage.getItem(stageKey(conversation.id)) || 'topic';
    selectedTopic = localStorage.getItem(`universe.conversation.topic.${conversation.id}`) || '';
    direction = localStorage.getItem(directionKey(conversation.id)) || '';
    selectedMode = conversation.mode;
    selectedSkill = conversation.skill_id || 'wechat_writer';
    syncSkillPicker();
    modeButtons.forEach(button => button.classList.toggle(
      'active', (button.dataset.mode === 'auto') === (selectedMode === 'auto'),
    ));
    localStorage.setItem(keyConversation, conversation.id);
    historyPopover.hidden = true;
    rememberConversationUrl(conversation.id);
    taskList.hidden = true; taskButton.setAttribute('aria-expanded', 'false');
    await refresh();
    status.textContent = '已恢复历史对话';
    if (conversation.active_run) restoreRun(conversation.active_run);
  }

  function rememberConversationUrl(id) {
    if (location.pathname !== '/workbench') return;
    const url = new URL(location.href);
    if (id) url.searchParams.set('conversation', id); else url.searchParams.delete('conversation');
    history.replaceState(null, '', url);
  }

  function restoreRun(run) {
    if (['queued', 'running'].includes(run.status)) watchRun(run.id, run);
    else if (run.status === 'waiting_input') {
      runtimeState = window.RunPresentation.create(run.id, run.stage || activeStage);
      applyRuntime({kind: 'snapshot', run}); setBusy(false);
    }
  }

  async function loadTaskList(more = false) {
    const epoch = accountEpoch;
    const sequence = ++taskReadSequence;
    taskList.innerHTML = '<p>正在读取任务…</p>';
    try {
      const data = await api('/api/runs?limit=50' + (more && taskCursor ? '&before=' + encodeURIComponent(taskCursor) : ''));
      if (epoch !== accountEpoch || sequence !== taskReadSequence) return;
      taskRows = more ? [...new Map([...taskRows, ...(data.runs || [])].map(run => [run.id, run])).values()] : data.runs || [];
      taskCursor = data.next_cursor || null;
      const rows = taskRows;
      taskList.innerHTML = '<h3>我的活动任务</h3><button type="button" data-refresh-runs>刷新状态</button>' + (rows.length ? rows.map(run => `
        <article><strong>${escapeHtml(run.conversation_title || '创作任务')}</strong>
        <p>${escapeHtml(stageLabel(run.stage))} · ${escapeHtml(({queued:'排队中',running:'执行中',waiting_input:'待补充'})[run.status] || run.status)}</p>
        <button type="button" data-conversation-id="${escapeHtml(run.conversation_id)}">进入任务</button>
        <button type="button" data-cancel-task="${escapeHtml(run.id)}">取消任务</button></article>`).join('')
        : '<p>当前没有待处理任务。已完成的作品可在「最近对话」中查看。</p>')
        + (taskCursor ? '<button type="button" data-more-runs>读取更早任务</button>' : '');
    } catch (error) {
      if (epoch !== accountEpoch || sequence !== taskReadSequence) return;
      taskList.innerHTML = `<p>${escapeHtml(error.message)}</p><button type="button" data-refresh-runs>重新读取</button>`;
    }
  }

  async function toggleConversationHistory() {
    taskList.hidden = true; taskButton.setAttribute('aria-expanded', 'false');
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

  function closeEvents() { source?.close(); source = null; clearInterval(runStatusTimer); runStatusTimer = null; }

  async function finishWatching(runId) {
    if (activeRun !== runId) return;
    closeEvents(); activeRun = null; localStorage.removeItem(keyRun); setBusy(false);
    await refresh().catch(error => appendNotice(error.message));
    if (runtimeState?.status === 'completed' && window.matchMedia('(max-width: 1100px)').matches) setOutputOpen(true);
  }

  function watchRun(runId, snapshot = null) {
    closeEvents(); activeRun = runId; localStorage.setItem(keyRun, runId);
    if (runtimeState?.id !== runId) runtimeState = window.RunPresentation.create(
      runId, activeStage, runtimeState?.id == null ? runtimeState?.createdAt : undefined);
    if (snapshot) applyRuntime({kind: 'snapshot', run: snapshot});
    setBusy(true, `正在生成${stages.find(item => item.id === activeStage)?.label || '当前成果'}`);
    setStep('submit', 'done');
    source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
    const types = ['run.created', 'run.queued', 'run.recovered', 'run.started', 'run.running', 'run.waiting_input',
      'skill.selected', 'stage.resolved', 'tool.started', 'tool.progress', 'tool.completed',
      'tool.failed', 'artifact.created', 'artifact.updated', 'assistant.completed',
      'run.completed', 'run.failed', 'run.cancelled'];
    types.forEach(type => source.addEventListener(type, async event => {
      if (activeRun !== runId) return;
      let payload = {};
      let record = {};
      try { record = JSON.parse(event.data || '{}'); payload = record.payload || {}; } catch { /* non-fatal */ }
      const previous = runtimeState;
      applyRuntime({kind: 'event', id: runId, type, payload, eventId: event.lastEventId, createdAt: record.created_at});
      if (previous === runtimeState && (event.lastEventId || record.created_at)) return;
      if (type === 'run.recovered') beginProgress(runtimeState.stage);
      if (type === 'run.started') { setStep('submit', 'done'); setStep('intent', 'active'); }
      if (type === 'stage.resolved') {
        // 模型决定了这一步做什么：切到对应标签并解释原因，避免"莫名跳 tab"。
        if (payload.stage && stages.some(item => item.id === payload.stage)) {
          if (payload.direction) direction = String(payload.direction);
          if (payload.selected_topic) selectedTopic = String(payload.selected_topic);
          // 重新出选题时旧的"已选方向"作废，避免拿旧标题去写大纲。
          if (payload.stage === 'topic' && payload.source === 'model') selectedTopic = '';
          selectStage(payload.stage);
          setStep('submit', 'done');
          setStep('intent', 'done');
          activateNextStep();
        }
        const reason = payload.reason || (payload.stage ? stageLabel(payload.stage) : '这是提问');
        appendProgress(`已理解：${reason}`, event.lastEventId);
        status.textContent = `已理解：${reason}`;
        return;
      }
      if (type === 'tool.progress') {
        const step = String(payload.step || '');
        if (step === 'hotspots') {
          const running = payload.status === 'running';
          setStep('hotspots', running ? 'active' : 'done',
                  running ? '正在抓取热点' : `热点 ${payload.count ?? 0} 条`);
          if (!running) setStep('search', 'active');
        } else if (step === 'search') {
          const running = payload.status === 'running';
          const fetched = payload.fetched ?? 0;
          setStep('search', running ? 'active' : 'done',
                  running ? '正在搜索参考'
                          : `搜索线索 ${payload.count ?? 0} 条${fetched ? ` · 抓取 ${fetched} 篇原文` : ''}`);
          if (!running) setStep('generating', 'active');
        } else if (step === 'generating') {
          setStep('generating', 'active', payload.label || '生成中');
        } else if (step === 'generated') {
          setStep('generating', 'done', payload.label || `已生成 ${payload.count ?? ''}`);
          setStep('saving', 'active');
        }
        status.textContent = progressNote || '正在执行';
        return;
      }
      if (type === 'tool.started') {
        setStep('generating', 'active');
      } else if (type === 'artifact.created' || type === 'assistant.completed') {
        setStep('saving', 'done');
      } else if (type === 'run.completed') {
        progressSteps.forEach(step => setStep(step.key, 'done'));
      } else if (type === 'run.failed') {
        const active = progressSteps.find(step => stepState[step.key] === 'active');
        if (active) setStep(active.key, 'failed');
      }
      if (type.startsWith('run.') && window.RunPresentation.terminal(type.slice(4))) appendProgress(eventText(type, payload), event.lastEventId);
      status.textContent = eventText(type, payload);
      if (['run.completed', 'run.failed', 'run.cancelled', 'run.waiting_input'].includes(type)) {
        await finishWatching(runId);
      }
    }));
    let checkingStatus = false;
    const reconcileStatus = async () => {
      if (checkingStatus || activeRun !== runId) return;
      checkingStatus = true;
      try {
        const run = (await api(`/api/runs/${encodeURIComponent(runId)}`, { signal: AbortSignal.timeout(10000) })).run;
        if (activeRun !== runId) return;
        applyRuntime({kind: 'snapshot', run});
        if (['completed', 'failed', 'cancelled', 'waiting_input'].includes(run.status)) {
          if (run.status === 'failed') {
            const message = failureText(run);
            appendProgress(message); status.textContent = message;
          }
          await finishWatching(runId);
        }
      } catch { /* Next poll and persisted replay can recover transient failures. */ }
      finally { checkingStatus = false; }
    };
    source.onopen = () => { if (activeRun === runId) applyRuntime({kind: 'connection.open'}); };
    source.onerror = () => {
      if (activeRun !== runId) return;
      applyRuntime({kind: 'connection.lost'}); reconcileStatus();
    };
    // An open SSE connection does not prove terminal events were delivered.
    runStatusTimer = setInterval(reconcileStatus, 8000);
    reconcileStatus();
  }

  async function submit(content = input.value.trim(), stage = activeStage, options = {}) {
    if (!content || send.disabled || submitting) return;
    const epoch = accountEpoch;
    submitting = true;
    runtimeState = window.RunPresentation.create(null, stage);
    applyRuntime({kind: 'saving'});
    const explicit = options.explicit === true;
    // 只有用户在选题里真的写了方向才更新；按钮用的固定句、模型判定都不覆盖。
    const canned = Object.values(defaultPrompt).includes(content);
    if (stage === 'topic' && !options.keepDirection && !canned && (explicit || !direction)) {
      direction = content;
    }
    if (conversation) {
      if (direction) localStorage.setItem(directionKey(conversation.id), direction);
      else localStorage.removeItem(directionKey(conversation.id));
    }
    let contentJson = { workflow_stage: stage, stage_explicit: explicit };
    if (stage === 'topic' && direction) contentJson.topic_direction = direction;
    if (selectedTopic) contentJson.selected_topic = selectedTopic;
    if (options.intent) contentJson.intent = options.intent;
    setBusy(true, explicit ? `正在执行：${stageLabel(stage)}` : '正在理解你的要求');
    let idempotencyKey;
    const draftInput = input.value;
    try {
      await flushEdits();
      if (epoch !== accountEpoch) return;
      applyRuntime({kind: 'submitting'});
      await ensureConversation();
      if (pendingSubmission?.conversationId === conversation.id && pendingSubmission.content === content) {
        contentJson = pendingSubmission.contentJson;
        stage = pendingSubmission.stage;
      }
      const fingerprint = JSON.stringify([conversation.id, content, contentJson]);
      if (pendingSubmission && pendingSubmission.fingerprint !== fingerprint) {
        const previous = await findPendingRun(pendingSubmission);
        if (!previous) throw new Error('上次提交尚未确认，请先重发原指令；暂未创建新任务');
        retainSubmission(null);
        if (['queued', 'running'].includes(previous.status)) {
          if (previous.conversation_id && previous.conversation_id !== conversation.id) await openConversation(previous.conversation_id);
          watchRun(previous.id);
          return;
        }
      }
      if (!pendingSubmission || pendingSubmission.fingerprint !== fingerprint) {
        retainSubmission({fingerprint, key: uuid(), conversationId: conversation.id, content, contentJson, stage});
      }
      idempotencyKey = pendingSubmission.key;
      input.value = '';
      appendProgress(explicit ? `正在执行：${stageLabel(stage)}` : '正在理解你的要求');
      const data = await api(`/api/conversations/${encodeURIComponent(conversation.id)}/messages`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ content, content_json: contentJson }),
        signal: AbortSignal.timeout(30000),
      });
      if (typeof data.run_id !== 'string' || !data.run_id) throw new Error('任务接收状态未确认，请稍后重试原请求');
      retainSubmission(null);
      watchRun(data.run_id);
      await refresh().catch(error => appendNotice(error.message));
    } catch (error) {
      if (epoch !== accountEpoch) return;
      // A definite 4xx means no new paid task was accepted. Transport failures
      // and 5xx responses retain the key because the commit may have succeeded.
      if (error.status >= 400 && error.status < 500) retainSubmission(null);
      setBusy(false);
      input.value = draftInput;
      appendNotice(error.message);
      if (pendingSubmission && pendingPersisted) appendNotice('提交结果尚未确认，记录已保留。刷新页面或重发原指令会继续确认同一请求。');
      if (pendingSubmission && !pendingPersisted) appendNotice('浏览器无法保留刷新后的重试记录，请先留在本页确认提交结果。');
    } finally {
      if (epoch === accountEpoch) submitting = false;
    }
  }

  // 按钮/标签驱动：阶段是用户明确点的，不再走模型判断（省一次调用，也保证确定性）。
  async function runStage(stage, extra = '', options = {}) {
    try { await flushEdits(); } catch (error) { appendNotice(error.message); return; }
    if (stage === 'topic' && stageArtifact('topic') && !options.keepTopic) {
      selectedTopic = '';
      if (conversation) localStorage.removeItem(`universe.conversation.topic.${conversation.id}`);
    }
    const text = String(extra || '').trim() || defaultPrompt[stage] || '继续这一步';
    selectStage(stage);
    submit(text, stage, { ...options, explicit: true });
  }

  async function restore() {
    const navigation = ++navigationSequence;
    localStorage.removeItem('universe.activeWorkflowId');
    const conversationId = new URLSearchParams(location.search).get('conversation') || localStorage.getItem(keyConversation);
    if (conversationId) {
      try {
        const next = (await api(`/api/conversations/${encodeURIComponent(conversationId)}`)).conversation;
        if (navigation !== navigationSequence) return;
        conversation = next;
        localStorage.setItem(keyConversation, conversation.id);
        activeStage = localStorage.getItem(stageKey(conversation.id)) || 'topic';
        selectedTopic = localStorage.getItem(`universe.conversation.topic.${conversation.id}`) || '';
        direction = localStorage.getItem(directionKey(conversation.id)) || '';
        selectedMode = conversation.mode;
        selectedSkill = conversation.skill_id || 'wechat_writer';
        syncSkillPicker();
        modeButtons.forEach(button => button.classList.toggle('active', (button.dataset.mode === 'auto') === (selectedMode === 'auto')));
        await refresh();
      } catch { conversation = null; localStorage.removeItem(keyConversation); }
    } else { renderMessages([]); renderArtifacts([]); }
    await recoverPendingSubmission();
    const runId = conversation?.active_run?.id || localStorage.getItem(keyRun);
    if (runId && conversation) {
      try {
        const run = (await api(`/api/runs/${encodeURIComponent(runId)}`)).run;
        if (['queued', 'running', 'waiting_input'].includes(run.status)) restoreRun(run);
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
      event.preventDefault(); event.stopImmediatePropagation();
      Promise.resolve().then(() => handler(target, event)).catch(error => appendNotice(error.message));
    }, true);
  }

  captureClick('#start-workbench', () => {
    const value = input.value.trim();
    if (!value) { input.focus(); return; }
    // 交给模型判断这一步要做什么；当前标签只作为上下文提示。
    submit(value, activeStage, { explicit: false });
  });
  captureClick('[data-workbench-stage]', async button => {
    await flushEdits();
    selectStage(button.dataset.workbenchStage);
  });
  captureClick('[data-topic-choice]', button => {
    const topics = stageArtifact('topic')?.content_json?.topics || [];
    const choice = topics[Number(button.dataset.topicChoice)];
    selectedTopic = String(typeof choice === 'string' ? choice : choice?.title || '').trim();
    if (!selectedTopic) return;
    const choiceIndex = button.dataset.topicChoice;
    if (conversation) localStorage.setItem(`universe.conversation.topic.${conversation.id}`, selectedTopic);
    renderStage();
    renderActionCard();
    window.requestAnimationFrame(() => {
      stageChoices.querySelector(`[data-topic-choice="${choiceIndex}"]`)?.focus({ preventScroll: true });
    });
  });
  captureClick('[data-retry-stage]', button => runStage(button.dataset.retryStage || activeStage));
  captureClick('[data-next-stage]', button => runStage(button.dataset.nextStage || activeStage));
  captureClick('[data-workbench-view-toggle]', () => setOutputOpen(true));
  captureClick('[data-focus-topics]', () => {
    const narrow = window.matchMedia?.('(max-width: 1100px)').matches;
    if (narrow) {
      setOutputOpen(true);
      window.setTimeout(() => {
        stageChoices.querySelector('[data-topic-choice]')?.focus({ preventScroll: true });
      }, 80);
      return;
    }
    stageChoices.scrollIntoView({ behavior: 'smooth', block: 'start' });
    stageChoices.querySelector('[data-topic-choice]')?.focus({ preventScroll: true });
  });
  captureClick('[data-copy-html]', async () => {
    await flushEdits();
    const item = stageArtifact('typeset');
    if (!item) { status.textContent = '还没有可复制的排版结果'; return; }
    if (window.PublisherCopy.isStale(item, latestOf('article'))) {
      status.textContent = '正文已更新，请重新排版后复制';
      return;
    }
    try {
      await window.PublisherCopy.copy(item);
      status.textContent = '已复制完整排版，请粘贴到公众号后台预览';
    } catch (error) { status.textContent = error.message; appendNotice(error.message); }
  });
  captureClick('#workbench-stage-next', () => {
    const index = stages.findIndex(item => item.id === activeStage);
    const target = isStale(activeStage) || !stageArtifact(activeStage)
      ? activeStage : stages[index + 1]?.id;
    if (target) runStage(target);
  });
  captureClick('#workbench-stage-rerun', () => runStage(activeStage));
  captureClick('#workbench-view-toggle', () => setOutputOpen(!outputOpen));
  captureClick('#new-workbench-chat', async () => {
    ++navigationSequence;
    try { await flushEdits(); } catch (error) { appendNotice(error.message); return; }
    closeEvents(); conversation = null; activeRun = null; renderedEventIds = new Set();
    runtimeState = null; root.removeAttribute('data-run-phase');
    rememberConversationUrl(null);
    savedHeads.clear();
    localStorage.removeItem(keyConversation); localStorage.removeItem(keyRun);
    activeStage = 'topic'; selectedTopic = ''; direction = ''; allArtifacts = []; lastMessages = [];
    submitting = false; setBusy(false); input.value = ''; renderMessages([]); renderArtifacts([]); status.textContent = '等待你的想法';
    syncSkillPicker();
  });
  captureClick('#recent-workbench-chats', () => toggleConversationHistory());
  captureClick('#active-workbench-runs', async () => {
    const open = taskList.hidden;
    historyPopover.hidden = true; taskList.hidden = !open;
    taskButton.setAttribute('aria-expanded', String(open));
    if (open) taskList.style.top = `${taskButton.getBoundingClientRect().bottom - root.getBoundingClientRect().top + 8}px`;
    if (open) await loadTaskList();
  });
  captureClick('[data-refresh-runs]', () => loadTaskList());
  captureClick('[data-more-runs]', () => loadTaskList(true));
  captureClick('[data-cancel-task]', async button => {
    button.disabled = true;
    try {
      if (button.dataset.cancelTask === activeRun) await cancelCurrentRun();
      else {
        const data = await api(`/api/runs/${encodeURIComponent(button.dataset.cancelTask)}/cancel`, {method:'POST'});
        if (runtimeState?.id === button.dataset.cancelTask) {
          applyRuntime({kind:'snapshot', run:data.run}); setBusy(false); await refresh();
        }
      }
      await loadTaskList();
    } catch (error) { appendNotice(error.message); button.disabled = false; }
  });
  captureClick('[data-resume-pending]', async () => {
    const record = pendingSubmission;
    if (!record) return;
    if (conversation?.id !== record.conversationId) await openConversation(record.conversationId);
    if (conversation?.id === record.conversationId) submit(record.content, record.stage);
  });
  captureClick('[data-conversation-id]', button => openConversation(button.dataset.conversationId));
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (!taskList.hidden) { taskList.hidden = true; taskButton.setAttribute('aria-expanded', 'false'); taskButton.focus(); }
    else if (!historyPopover.hidden) { historyPopover.hidden = true; root.querySelector('#recent-workbench-chats').focus(); }
  });
  document.addEventListener('click', event => {
    if (!taskList.contains(event.target) && !taskButton.contains(event.target)) {
      taskList.hidden = true; taskButton.setAttribute('aria-expanded', 'false');
    }
  });
  async function cancelCurrentRun() {
    if (!activeRun || (runtimeState?.cancelRequested && !runtimeState.cancelUnconfirmed)) return;
    const id = activeRun;
    applyRuntime({kind: 'cancel.requested'});
    try {
      const data = await api(`/api/runs/${encodeURIComponent(id)}/cancel`, {method: 'POST', signal: AbortSignal.timeout(10000)});
      if (activeRun !== id) return;
      applyRuntime({kind: 'snapshot', run: data.run});
      if (window.RunPresentation.terminal(runtimeState.status)) await finishWatching(id);
    } catch (error) {
      if (activeRun !== id || window.RunPresentation.terminal(runtimeState?.status)) return;
      applyRuntime({kind:'cancel.unconfirmed'});
      if (error.status === 401 || error.status === 403) appendNotice('登录状态已变化，请重新登录后核对取消结果。');
    }
  }
  captureClick('#cancel-workbench, [data-cancel-run]', () => cancelCurrentRun());
  captureClick('#workbench-regenerate-topics', () => {
    // 「换一批方向」要真的换一批：先切回选题阶段，再沿用原方向重跑。
    selectStage('topic');
    if (!direction && !stageArtifact('topic')) { input.focus(); status.textContent = '先告诉我你想写什么方向'; return; }
    runStage('topic', '再换一批方向，角度更具体，别和上一批重复',
             { keepTopic: true, keepDirection: true });
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
  captureClick('#version-back', async () => {
    await flushEdits();
    if (!editableArtifacts.length) return;
    await openArtifact(editableArtifacts[Math.max(0, artifactIndex - 1)]);
  });
  captureClick('#version-forward', async () => {
    await flushEdits();
    if (!editableArtifacts.length) return;
    await openArtifact(editableArtifacts[Math.min(editableArtifacts.length - 1, artifactIndex + 1)]);
  });
  captureClick('#edit-current', () => {
    if (!currentArtifact || editor.readOnly) return;
    if (!editor.closest('.editor-wrap')?.classList.contains('is-editing')) document.querySelector('.folio-doc-edit')?.click();
    editor.focus();
  });
  captureClick('#copy-current-artifact', async () => {
    await flushEdits();
    if (!currentArtifact) return;
    if (currentArtifact.type === 'html' && currentArtifact.id === stageArtifact('typeset')?.id &&
        window.PublisherCopy.isStale(currentArtifact, latestOf('article'))) {
      saveState.textContent = '正文已更新，请重新排版后复制';
      return;
    }
    try {
      if (currentArtifact.type === 'html') await window.PublisherCopy.copy(currentArtifact);
      else await navigator.clipboard.writeText(editor.value || currentArtifact.content || '');
      saveState.textContent = '已复制当前作品';
    } catch (error) { saveState.textContent = error.message || '浏览器未允许复制'; }
  });
  captureClick('#download-current-artifact', async () => {
    await flushEdits();
    if (!currentArtifact) return;
    const extension = currentArtifact.type === 'html' ? 'html' : currentArtifact.type === 'markdown' ? 'md' : 'txt';
    const blob = new Blob([currentArtifact.type === 'html' ? currentArtifact.content : (editor.value || currentArtifact.content || '')], {
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
    const value = input.value.trim();
    if (!value) { input.focus(); return; }
    submit(value, activeStage, { explicit: false });
  }, true);
  editor.addEventListener('input', () => {
    if (!currentArtifact || editor.readOnly || editor.value === (currentArtifact.content || '')) return;
    clearTimeout(saveTimer);
    const sequence = ++editSequence;
    const artifact = currentArtifact;
    const content = editor.value;
    saveState.textContent = '正在保存修改…';
    pendingEdit = [sequence, artifact, content];
    saveTimer = setTimeout(() => flushEdits().catch(() => {}), 900);
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

  window.addEventListener('before-account-change', event => {
    event.detail.pending.push(flushEdits());
  });
  window.addEventListener('account-changed', () => {
    const next = typeof currentAccount !== 'undefined' ? currentAccount?.id || null : null;
    if (accountId === undefined) { accountId = next; return; }
    if (next === accountId) return;
    accountId = next; accountEpoch++;
    ++navigationSequence;
    closeEvents(); endProgress(); clearTimeout(saveTimer);
    pendingEdit = null; retainSubmission(null); savedHeads.clear(); editSequence++;
    savingEdits = 0; deferredRefresh = false;
    conversation = null; activeRun = null; currentArtifact = null;
    taskList.hidden = true; taskList.textContent = ''; taskButton.setAttribute('aria-expanded', 'false');
    taskRows = []; taskCursor = null; ++taskReadSequence;
    runtimeState = null; root.removeAttribute('data-run-phase');
    allArtifacts = []; editableArtifacts = []; lastMessages = [];
    artifactTotal = 0; artifactCursor = null;
    selectedTopic = ''; direction = ''; activeStage = 'topic';
    localStorage.removeItem(keyConversation); localStorage.removeItem(keyRun);
    rememberConversationUrl(null);
    input.value = ''; htmlPreview.srcdoc = ''; renderedEventIds.clear();
    root.querySelector('.draft-recovery')?.setAttribute('hidden', '');
    root.querySelectorAll('.folio-doc').forEach(node => { node.textContent = ''; });
    const landingInput = root.querySelector('#folio-ask');
    if (landingInput) landingInput.value = '';
    const writerFrame = document.querySelector('#one-click-writing-frame');
    if (writerFrame) {
      writerFrame.removeAttribute('src');
      if (next && !document.querySelector('#one-click-writing')?.hidden) writerFrame.src = writerFrame.dataset.src;
    }
    setBusy(false); renderMessages([]); renderArtifacts([]); syncSkillPicker();
  });
  window.addEventListener('beforeunload', event => {
    if (!pendingEdit && !savingEdits && (!pendingSubmission || pendingPersisted)) return;
    event.preventDefault(); event.returnValue = '';
  });
  syncSkillPicker();
  loadSkills();
  restore();
})();
