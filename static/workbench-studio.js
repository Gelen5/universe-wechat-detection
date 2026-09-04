(() => {
  const workspace = document.querySelector('#workbench');
  const details = document.querySelector('#studio-details');
  const toggle = document.querySelector('#studio-details-toggle');
  const tabs = [...document.querySelectorAll('[data-studio-view]')];
  const layout = workspace.querySelector('.conversation-workbench-layout');
  const stage = document.querySelector('#studio-stage-output');
  const decision = document.querySelector('#workbench-decision');
  // Keep actual generated choices beside the current-step instruction.
  stage.append(document.querySelector('#topic-list'));
  const framework = document.createElement('div');
  framework.className = 'studio-framework';
  stage.append(framework);
  let previousStage = 0;
  function syncStage() {
    const session = workbenchSession;
    const step = session?.current_step || 0;
    workspace.dataset.stage = String(step);
    workspace.querySelector('.editor-wrap').hidden = !session?.article;
    workspace.querySelector('.article-canvas-foot').hidden = !session?.article;
    document.querySelector('#workbench-regenerate-topics').hidden = step !== 1;
    document.querySelector('#edit-current').disabled = !session?.article;
    document.querySelector('#version-back').disabled = !session?.versions?.length;
    document.querySelector('#version-forward').disabled = !session?.versions?.length;
    framework.hidden = step !== 2;
    framework.replaceChildren();
    if (step === 2) {
      const heading = document.createElement('h3');
      heading.textContent = session.framework?.name || '文章框架';
      const list = document.createElement('ol');
      (session.framework?.outline || []).forEach(text => { const li = document.createElement('li'); li.textContent = text; list.append(li); });
      framework.append(heading, list);
    }
    if (!step) renderDecisionPanel(null);
    if (step && step !== previousStage) setView('article');
    previousStage = step;
  }
  // Session rendering updates the title after assigning state. Observe that narrow
  // target so this presentation layer does not interfere with request handling.
  new MutationObserver(syncStage).observe(document.querySelector('#result-title'), { childList:true });
  syncStage();
  const send = document.querySelector('#start-workbench');
  function syncSend() {
    send.setAttribute('aria-busy', String(send.disabled));
    send.setAttribute('aria-label', send.disabled ? '正在生成，请稍候' : '发送需求');
    document.querySelector('#new-workbench-chat').disabled = send.disabled || !!workbenchController;
    if (send.disabled && !workbenchSession) {
      document.querySelector('#workbench-status').textContent = '正在生成选题';
      document.querySelector('#flow-step-label').textContent = '正在整理你的需求';
      document.querySelector('#flow-step-hint').textContent = '选题生成后，请选择一个方向继续';
    } else if (!workbenchSession) {
      document.querySelector('#workbench-status').textContent = '等待你的想法';
      renderDecisionPanel(null);
    }
  }
  new MutationObserver(syncSend).observe(send, { attributes:true, attributeFilter:['disabled'] });
  // Progress must remain reachable even with the optional inspector closed.
  layout.append(document.querySelector('#workbench-progress'));
  function setDetails(open) {
    details.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
  }
  toggle.addEventListener('click', () => setDetails(details.hidden));
  workspace.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !details.hidden) {
      setDetails(false);
      toggle.focus();
    }
  });
  function setView(view) {
    workspace.dataset.studioView = view;
    tabs.forEach(tab => tab.setAttribute('aria-pressed', String(tab.dataset.studioView === view)));
  }
  tabs.forEach(tab => tab.addEventListener('click', () => setView(tab.dataset.studioView)));
  // Existing workflow navigation can reveal content in the closed inspector/mobile pane.
  document.querySelector('#workflow-steps').addEventListener('click', event => {
    const step = event.target.closest('.clickable');
    if (!step) return;
    if (step.dataset.step === '2') setDetails(true);
    else if (Number(step.dataset.step) > 2) setView('article');
  }, true);
  document.querySelector('#workbench-version-list').addEventListener('click', event => {
    if (!event.target.closest('.version-item')) return;
    setView('article');
    setDetails(false);
  });
  document.querySelector('#edit-current').addEventListener('click', () => setView('article'));
  setView('chat');
  document.querySelector('#new-workbench-chat').addEventListener('click', () => {
    paintWorkflow(1);
    renderDecisionPanel(null);
    document.querySelector('#score-report').hidden = true;
    document.querySelector('#generated-images').hidden = true;
    document.querySelector('#download-workbench-html').hidden = true;
    setDetails(false);
    setView('chat');
    syncStage();
    document.querySelector('#workbench-topic').focus();
  });
})();
