(() => {
  const definitions = [
    ['xiaohongshu', '#xiaohongshu .skill-form-col', renderXhsPackage],
    ['tie-tu', '#tie-tu .skill-form-col', renderTiePlan],
    ['hit-detector', '#hit-detector .skill-form-col', artifact => {
      if (artifact.report) renderHitReport(artifact.report);
      if (artifact.article) {
        document.querySelector('#hit-title').value = artifact.article.title;
        document.querySelector('#hit-body').value = artifact.article.body;
      }
    }],
    ['diagnose', '#diagnose .v3-hero-l', (artifact, output) => {
      if (!artifact.report) return;
      renderReport(artifact.report, false);
      output.replaceChildren();
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'secondary-action';
      button.textContent = '查看完整诊断报告';
      button.onclick = () => setActiveView('report');
      output.append(button);
    }],
    ['morning', '#morning-generator .morning-intro', renderMorning],
  ];

  function download(name, content, type) {
    const url = URL.createObjectURL(new Blob([content], {type}));
    const a = document.createElement('a'); a.href = url; a.download = name; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function renderMorning(draft, output) {
    const images = (draft.images || []).map(image => `<img src="${esc(safeUrl(image.url))}" alt="早安祝福图" style="display:inline-block;width:${Math.floor(100 / (draft.columns || 1))}%;height:auto;vertical-align:top;">`).join('');
    const copies = draft.copies || [];
    const position = Math.min(copies.length, draft.image_at || 1) - 1;
    const content = copies.map((copy, i) => `${i === position && draft.image_position === 'before' ? images : ''}<p>${esc(copy)}</p>${i === position && draft.image_position !== 'before' ? images : ''}`).join('');
    const html = `<article style="font-family:system-ui;line-height:1.8;color:#222"><h2>${esc(draft.title || '早安祝福')}</h2>${content}</article>`;
    output.innerHTML = html;
    const txt = document.createElement('button'); txt.type = 'button'; txt.className = 'secondary-action';
    txt.textContent = '下载文案'; txt.onclick = () => download('早安文案.txt', copies.join('\n\n'), 'text/plain');
    output.append(txt);
    if (draft.mode !== 'sticker') {
      const exportButton = document.createElement('button'); exportButton.type = 'button'; exportButton.className = 'secondary-action';
      exportButton.textContent = '下载 HTML';
      exportButton.onclick = async () => {
        exportButton.disabled = true;
        try {
          const article = output.querySelector('article').cloneNode(true);
          for (const image of article.querySelectorAll('img')) {
            const response = await fetch(image.src);
            if (!response.ok) throw new Error('图片下载失败，请重试');
            const blob = await response.blob();
            image.src = await new Promise((resolve, reject) => {
              const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(blob);
            });
          }
          download('早安祝福.html', '<!doctype html><meta charset="utf-8">' + article.outerHTML, 'text/html');
        } catch (error) { showToast(error.message, 'error'); }
        finally { exportButton.disabled = false; }
      };
      output.append(exportButton);
    }
    if (draft.cards?.length && (draft.images || []).length < draft.cards.length) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'primary-action'; button.textContent = '确认并生成图片';
      button.onclick = () => window.dispatchEvent(new CustomEvent('creator-chat-send', {detail: {skill: 'morning', message: '确认当前图片计划，生成全部尚未生成的图片'}}));
      output.append(button);
      const plan = document.createElement('p'); plan.textContent = draft.cards.map(card => `${card.index}. ${card.headline}：${card.scene || ''}`).join('\n'); output.append(plan);
    }
    for (const image of draft.images || []) {
      const a = document.createElement('a'); a.href = safeUrl(image.url); a.download = `早安-${image.index}.png`; a.textContent = `下载图片 ${image.index}`; output.append(a);
    }
  }

  for (const [skill, selector, render] of definitions) {
    const column = document.querySelector(selector);
    if (!column) continue;
    let session = null, artifact = null, owner = null, controller = null, restoring = false;
    const form = document.createElement('form'); form.className = 'skill-form creator-conversation';
    const history = document.createElement('div'); history.className = 'creator-chat-history'; history.setAttribute('role', 'log'); history.setAttribute('aria-label', '创作对话');
    const label = document.createElement('label'); label.textContent = skill === 'tie-tu' ? '用对话提要求' : '告诉我你想做什么';
    const input = document.createElement('textarea'); input.required = true; input.maxLength = 4000; input.rows = 3; label.append(input);
    if (skill === 'tie-tu') input.placeholder = '例如：做 3 张关于下班后放松的图文，风格温暖清晰';
    const button = document.createElement('button'); button.type = 'submit'; button.className = 'primary-action'; button.textContent = '发送';
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'secondary-action'; cancel.textContent = '取消'; cancel.hidden = true; cancel.onclick = () => controller?.abort();
    const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'secondary-action'; reset.textContent = '新对话';
    const status = document.createElement('p'); status.setAttribute('role', 'status');
    const progress = document.createElement('progress'); progress.hidden = true; progress.setAttribute('aria-label', '正在执行');
    const output = document.createElement('div'); output.className = 'creator-chat-output';
    form.append(history, label, button, cancel, reset, progress, status, output);
    try {
      const draft = JSON.parse(sessionStorage.getItem('universe.creatorHomeDraft') || 'null');
      if (draft && draft.target === location.pathname && draft.target.slice(1) === skill) {
        input.value = String(draft.text || '');
        sessionStorage.removeItem('universe.creatorHomeDraft');
      }
    } catch { sessionStorage.removeItem('universe.creatorHomeDraft'); }

    const existing = Array.from(column.children).find(child => child.tagName === 'FORM');
    if (skill === 'tie-tu' && existing) existing.after(form);
    else column.insertBefore(form, existing || null);
    const legacy = skill === 'morning' ? document.querySelector('#morning-generator .morning-frame-wrap') : existing;
    let selectTieMode = null;
    if (legacy && skill !== 'tie-tu') {
      const details = document.createElement('details'); details.className = 'creator-form-mode';
      const summary = document.createElement('summary'); summary.textContent = skill === 'tie-tu' ? '用表单创建计划' : '表单模式';
      legacy.before(details); details.append(summary, legacy);
    } else if (legacy && skill === 'tie-tu') {
      const modes = document.createElement('div'); modes.className = 'tie-mode-switch';
      modes.setAttribute('role', 'group'); modes.setAttribute('aria-label', '选择创建方式');
      modes.innerHTML = '<button type="button" data-tie-mode="form">表单创建</button><button type="button" data-tie-mode="chat">对话创建</button>';
      const hint = document.createElement('p'); hint.className = 'tie-mode-hint';
      const activity = document.createElement('p'); activity.className = 'tie-mode-activity'; activity.setAttribute('role', 'status'); activity.hidden = true;
      legacy.before(modes, hint, activity);
      selectTieMode = mode => {
        const isForm = mode === 'form';
        legacy.hidden = !isForm; form.hidden = isForm;
        modes.querySelectorAll('button').forEach(tab => tab.setAttribute('aria-pressed', String(tab.dataset.tieMode === mode)));
        hint.textContent = isForm ? '填写主题，点击生成卡片计划。' : '直接说出想做的内容，可继续对话调整。';
        const emptyHint = document.querySelector('#tie-empty .empty-head p');
        if (emptyHint) emptyHint.textContent = isForm ? '填写左侧表单，点击“生成卡片计划”。' : '在左侧说出你的想法，发送后生成计划。';
      };
      modes.addEventListener('click', event => { const tab = event.target.closest('[data-tie-mode]'); if (tab) selectTieMode(tab.dataset.tieMode); });
      const updateActivity = () => {
        const pending = [];
        if (document.querySelector('#tie-plan')?.disabled) pending.push('表单计划正在生成');
        if (controller) pending.push('对话任务正在处理');
        activity.textContent = pending.length ? pending.join('；') + '，请勿重复提交。' : '';
        activity.hidden = !pending.length;
      };
      new MutationObserver(updateActivity).observe(document.querySelector('#tie-plan'), {attributes:true, attributeFilter:['disabled']});
      new MutationObserver(updateActivity).observe(button, {attributes:true, attributeFilter:['disabled']});
      selectTieMode(input.value ? 'chat' : 'form');
    }
    if (skill === 'tie-tu') {
      document.querySelectorAll('#tie-tu .style-chip').forEach(chip => chip.addEventListener('click', () => {
        const style = document.querySelector('#tie-style');
        if (!style) return;
        selectTieMode?.('form');
        style.value = chip.dataset.style || '';
        const details = style.closest('details');
        if (details) details.open = true;
        style.focus();
      }));
    }
    const storageKey = () => `creator-chat:${owner}:${skill}`;
    function show(next) {
      session = next;
      history.replaceChildren();
      for (const message of session.conversation || []) {
        const paragraph = document.createElement('p'); paragraph.textContent = `${message.role === 'user' ? '你' : '助手'}：${message.content}`; history.append(paragraph);
      }
      history.scrollTop = history.scrollHeight;
      const draft = ['hit-detector', 'diagnose'].includes(skill) ? session.artifacts : session.artifacts?.draft;
      if (draft && JSON.stringify(draft) !== artifact) { render(draft, output); artifact = JSON.stringify(draft); }
      if (owner) localStorage.setItem(storageKey(), session.id);
    }
    async function restore() {
      const nextOwner = currentAccount?.id || null;
      if (owner === nextOwner) return;
      controller?.abort(); owner = nextOwner; session = null; artifact = null; history.replaceChildren(); output.replaceChildren();
      const id = owner && localStorage.getItem(storageKey());
      if (!id) return;
      restoring = true; button.disabled = true; reset.disabled = true;
      try {
        const response = await fetch(`/api/creator/chat/${encodeURIComponent(id)}`);
        if (response.ok) { const data = await response.json(); if (owner === nextOwner) show(data.session); }
        else if (response.status === 404) localStorage.removeItem(storageKey());
      } catch { status.textContent = '会话恢复失败，请刷新重试'; }
      finally { restoring = false; button.disabled = !!controller; reset.disabled = !!controller; }
    }
    reset.onclick = () => { if (controller) return; session = null; artifact = null; history.replaceChildren(); output.replaceChildren(); if (owner) localStorage.removeItem(storageKey()); status.textContent = ''; };
    window.addEventListener('creator-account-changed', restore); restore();
    window.addEventListener('creator-chat-send', event => {
      if (event.detail.skill !== skill || controller) return;
      input.value = event.detail.message; form.requestSubmit();
    });
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (controller || restoring || !input.value.trim()) return;
      controller = new AbortController(); button.disabled = true; reset.disabled = true; cancel.hidden = false; progress.hidden = false;
      const imageButton = skill === 'tie-tu' ? document.querySelector('#tie-images') : null;
      const imageLabel = imageButton?.textContent;
      if (imageButton) { imageButton.disabled = true; imageButton.setAttribute('aria-busy', 'true'); imageButton.textContent = '正在处理 · 0 秒'; }
      const requestOwner = owner;
      const started = Date.now(); let jobStatus = 'queued'; status.textContent = '正在提交…';
      const timer = setInterval(() => { if (imageButton?.isConnected) imageButton.textContent = `正在处理 · ${Math.floor((Date.now()-started)/1000)} 秒`; status.textContent = `${jobStatus === 'queued' ? '等待任务执行' : '正在处理'} · ${Math.floor((Date.now()-started)/1000)} 秒`; }, 1000);
      try {
        const data = await submitQueuedTask('creator_chat', {skill, message: input.value.trim(), session_id: session?.id || null}, controller.signal, job => {
          jobStatus = job.status || jobStatus;
          if (job.session_id && owner === requestOwner) {
            session = session || {id: job.session_id};
            if (owner) localStorage.setItem(storageKey(), job.session_id);
          }
        });
        if (owner !== requestOwner) return;
        show(data.session); input.value = ''; status.textContent = '已完成';
      } catch (error) {
        if (owner !== requestOwner) return;
        status.textContent = error.name === 'AbortError' ? '已请求取消，已完成图片仍会保留' : error.message;
        if (session?.id) {
          const response = await fetch(`/api/creator/chat/${encodeURIComponent(session.id)}`).catch(() => null);
          if (response?.ok) { const data = await response.json(); if (owner === requestOwner) show(data.session); }
        }
      } finally {
        if (imageButton?.isConnected) { imageButton.disabled = false; imageButton.removeAttribute('aria-busy'); imageButton.textContent = imageLabel; }
        clearInterval(timer); controller = null; button.disabled = false; reset.disabled = false; cancel.hidden = true; progress.hidden = true;
      }
    });
  }
})();
