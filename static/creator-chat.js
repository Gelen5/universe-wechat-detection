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
    const label = document.createElement('label'); label.textContent = '告诉我你想做什么';
    const input = document.createElement('textarea'); input.required = true; input.maxLength = 4000; input.rows = 3; label.append(input);
    const button = document.createElement('button'); button.type = 'submit'; button.className = 'primary-action'; button.textContent = '发送';
    const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'secondary-action'; cancel.textContent = '取消'; cancel.hidden = true; cancel.onclick = () => controller?.abort();
    const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'secondary-action'; reset.textContent = '新对话';
    const status = document.createElement('p'); status.setAttribute('role', 'status');
    const progress = document.createElement('progress'); progress.hidden = true; progress.setAttribute('aria-label', '正在执行');
    const output = document.createElement('div'); output.className = 'creator-chat-output';
    form.append(history, label, button, cancel, reset, progress, status, output);
    const existing = Array.from(column.children).find(child => child.tagName === 'FORM');
    column.insertBefore(form, existing || null);
    const legacy = skill === 'morning' ? document.querySelector('#morning-generator .morning-frame-wrap') : existing;
    if (legacy) {
      const details = document.createElement('details'); details.className = 'creator-form-mode';
      const summary = document.createElement('summary'); summary.textContent = '表单模式';
      legacy.before(details); details.append(summary, legacy);
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
      const requestOwner = owner;
      const started = Date.now(); status.textContent = '正在提交…';
      const timer = setInterval(() => { status.textContent = `正在处理 · ${Math.floor((Date.now()-started)/1000)} 秒`; }, 1000);
      try {
        const data = await submitQueuedTask('creator_chat', {skill, message: input.value.trim(), session_id: session?.id || null}, controller.signal, job => {
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
        clearInterval(timer); controller = null; button.disabled = false; reset.disabled = false; cancel.hidden = true; progress.hidden = true;
      }
    });
  }
})();
