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
  const directionKey = id => `universe.conversation.direction.${id}`;
  const stages = [
    { id: 'topic', label: '选题', hint: '输入主题，选择一个值得写的方向。' },
    { id: 'outline', label: '大纲', hint: '确认文章结构；可以直接修改大纲。' },
    { id: 'writing', label: '写作', hint: '根据确认的大纲生成正文。' },
    { id: 'deai', label: '去 AI', hint: '保留原意，检查事实与表达并生成修订稿。' },
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
      progressTitle.textContent = `正在执行：${stageLabel(progressStage)}`;
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
    progressStartedAt = Date.now();
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
  let direction = '';
  let lastMessages = [];

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

  function firstMissingStage() {
    if (!stageArtifact('topic')) return 'topic';
    if (!selectedTopic) return null;
    if (!stageArtifact('outline')) return 'outline';
    if (!stageArtifact('writing')) return 'writing';
    if (!stageArtifact('deai')) return 'deai';
    if (!stageArtifact('typeset')) return 'typeset';
    return null;
  }

  function latestFailure() {
    const last = [...lastMessages].reverse().find(message => message.role === 'assistant');
    return last && messageMeta(last).kind === 'run_failed' ? last : null;
  }

  // 阶段不再由前端按关键词猜：一句话交给后端的意图调度（server/agent/intent.py），
  // 由模型结合当前进度判断；按钮/标签点击才是显式指定阶段。
  function renderActionCard() {
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
      html = `<strong>正在执行：${escapeHtml(stageLabel(progressStage || activeStage))}</strong>
        <ol class="chat-steps">${steps}</ol>
        <p><span id="chat-elapsed">已等待 ${elapsed}</span>${progressNote ? ` · ${escapeHtml(progressNote)}` : ''}</p>
        <p class="chat-steps-hint">这一步通常要 1–4 分钟，可以离开页面，任务不会丢。</p>`;
    } else if (failure) {
      const meta = messageMeta(failure);
      const stage = meta.stage || activeStage;
      html = `<strong>${escapeHtml(stageLabel(stage))}这一步没有完成</strong>
        <p>原因和积分状态见上方卡片。重试只重跑这一步，已完成的阶段不会丢。</p>
        <div class="chat-action-row">
          <button type="button" class="chat-action-primary" data-retry-stage="${escapeHtml(stage)}">重试：${escapeHtml(stageLabel(stage))}</button>
        </div>`;
    } else if (!topicItem) {
      html = `<strong>先告诉我你想写什么</strong>
        <p>一句话就够，例如「写一篇给 30 岁职场人的 AI 工具实测」。</p>`;
    } else if (!selectedTopic) {
      const topics = (topicItem.content_json?.topics || []).slice(0, 6);
      html = `<strong>选一个方向开始写</strong>
        <p>选完就能直接生成大纲，也可以在作品区挑。</p>
        <div class="chat-choice-row">${topics.map((choice, position) => {
          const name = String(typeof choice === 'string' ? choice : choice.title || '').trim();
          return `<button type="button" data-topic-choice="${position}">${escapeHtml(name)}</button>`;
        }).join('')}</div>
        ${topics.length ? '' : `<div class="chat-action-row">
          <button type="button" class="chat-action-primary" data-retry-stage="topic">重新生成选题</button>
        </div>`}`;
    } else if (next) {
      html = `<strong>下一步：${escapeHtml(stageLabel(next))}</strong>
        <p>已选方向《${escapeHtml(selectedTopic)}》。已完成的阶段都会保留。</p>
        <div class="chat-action-row">
          <button type="button" class="chat-action-primary" data-next-stage="${next}">继续：${escapeHtml(stageLabel(next))}</button>
          ${next === 'typeset' ? '' : '<button type="button" class="chat-action-ghost" data-next-stage="typeset">直接排版</button>'}
        </div>`;
    } else {
      html = `<strong>这篇稿子已经排好版</strong>
        <p>复制到公众号后台即可。要改正文就点「查看作品」直接编辑，改动会自动保存成新版本；说「重新排版」可以再来一次。</p>
        <div class="chat-action-row">
          <button type="button" class="chat-action-primary" data-copy-html>复制 HTML</button>
          <button type="button" class="chat-action-ghost" data-workbench-view-toggle>查看作品</button>
        </div>`;
    }
    card.innerHTML = html;
    thread.append(card);
    thread.scrollTop = thread.scrollHeight;
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
    renderActionCard();
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
    direction = localStorage.getItem(directionKey(conversation.id)) || '';
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
      'skill.selected', 'stage.resolved', 'tool.started', 'tool.progress', 'tool.completed',
      'tool.failed', 'artifact.created', 'artifact.updated', 'assistant.completed',
      'run.completed', 'run.failed', 'run.cancelled'];
    types.forEach(type => source.addEventListener(type, async event => {
      let payload = {};
      try { payload = JSON.parse(event.data || '{}').payload || {}; } catch { /* non-fatal */ }
      if (type === 'stage.resolved') {
        // 模型决定了这一步做什么：切到对应标签并解释原因，避免"莫名跳 tab"。
        if (payload.stage && stages.some(item => item.id === payload.stage)) {
          if (payload.direction) direction = String(payload.direction);
          if (payload.selected_topic) selectedTopic = String(payload.selected_topic);
          // 重新出选题时旧的"已选方向"作废，避免拿旧标题去写大纲。
          if (payload.stage === 'topic' && payload.source === 'model') selectedTopic = '';
          selectStage(payload.stage);
          if (!progress.hidden) beginProgress(payload.stage);
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
          setStep('search', running ? 'active' : 'done',
                  running ? '正在搜索参考' : `搜索线索 ${payload.count ?? 0} 条`);
          if (!running) setStep('generating', 'active');
        } else if (step === 'generating') {
          setStep('generating', 'active', payload.label || '生成中');
        } else if (step === 'generated') {
          setStep('generating', 'done', payload.label || `已生成 ${payload.count ?? ''}`);
          setStep('saving', 'active');
        }
        appendProgress(progressNote || '正在执行', event.lastEventId);
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

  async function submit(content = input.value.trim(), stage = activeStage, options = {}) {
    if (!content || send.disabled || submitting) return;
    submitting = true;
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
    const contentJson = { workflow_stage: stage, stage_explicit: explicit };
    if (stage === 'topic' && direction) contentJson.topic_direction = direction;
    if (selectedTopic) contentJson.selected_topic = selectedTopic;
    if (options.intent) contentJson.intent = options.intent;
    setBusy(true, explicit ? `正在执行：${stageLabel(stage)}` : '正在理解你的要求');
    const idempotencyKey = uuid();
    const draftInput = input.value;
    try {
      await ensureConversation();
      input.value = '';
      appendProgress(explicit ? `正在执行：${stageLabel(stage)}` : '正在理解你的要求');
      const data = await api(`/api/conversations/${encodeURIComponent(conversation.id)}/messages`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'Idempotency-Key': idempotencyKey },
        body: JSON.stringify({ content, content_json: contentJson }),
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

  // 按钮/标签驱动：阶段是用户明确点的，不再走模型判断（省一次调用，也保证确定性）。
  function runStage(stage, extra = '', options = {}) {
    if (stage === 'topic' && stageArtifact('topic') && !options.keepTopic) {
      selectedTopic = '';
      if (conversation) localStorage.removeItem(`universe.conversation.topic.${conversation.id}`);
    }
    const text = String(extra || '').trim() || defaultPrompt[stage] || '继续这一步';
    selectStage(stage);
    submit(text, stage, { ...options, explicit: true });
  }

  async function restore() {
    localStorage.removeItem('universe.activeWorkflowId');
    const conversationId = localStorage.getItem(keyConversation);
    if (conversationId) {
      try {
        conversation = (await api(`/api/conversations/${encodeURIComponent(conversationId)}`)).conversation;
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
    if (!value) { input.focus(); return; }
    // 交给模型判断这一步要做什么；当前标签只作为上下文提示。
    submit(value, activeStage, { explicit: false });
  });
  captureClick('[data-workbench-stage]', button => selectStage(button.dataset.workbenchStage));
  captureClick('[data-topic-choice]', button => {
    const topics = stageArtifact('topic')?.content_json?.topics || [];
    const choice = topics[Number(button.dataset.topicChoice)];
    selectedTopic = String(typeof choice === 'string' ? choice : choice?.title || '').trim();
    if (!selectedTopic) return;
    if (conversation) localStorage.setItem(`universe.conversation.topic.${conversation.id}`, selectedTopic);
    renderStage();
    renderActionCard();
  });
  captureClick('[data-retry-stage]', button => runStage(button.dataset.retryStage || activeStage));
  captureClick('[data-next-stage]', button => runStage(button.dataset.nextStage || activeStage));
  captureClick('[data-workbench-view-toggle]', () => setOutputOpen(true));
  captureClick('[data-copy-html]', async () => {
    const item = stageArtifact('typeset');
    if (!item) { status.textContent = '还没有可复制的排版结果'; return; }
    try {
      await navigator.clipboard.writeText(item.content || '');
      status.textContent = 'HTML 已复制，粘贴到公众号后台即可';
    } catch { status.textContent = '浏览器未允许复制，请到作品区手动复制'; }
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
    activeStage = 'topic'; selectedTopic = ''; direction = ''; allArtifacts = []; lastMessages = [];
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
