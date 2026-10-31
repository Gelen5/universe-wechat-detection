/* Independent conversational workspace; no legacy creator state is reused. */
(() => {
  const root = document.querySelector('#wechat-plus');
  if (!root) return;
  const $ = name => root.querySelector(`[data-wp-${name}]`);
  let session = null, active = null, owner = null, epoch = 0, loading = false;
  let timer = null, polling = false, dirty = false, saving = null, pending = null;
  let selectedTab = 'draft', shownVersion = '', previewKey = '';
  const key = suffix => `universe.wechat-plus.${owner}.${suffix}`;
  const uuid = () => crypto.randomUUID?.() || Array.from(crypto.getRandomValues(new Uint8Array(16)), value => value.toString(16).padStart(2, '0')).join('');
  const messageRoot = $('messages'), editor = $('editor');
  const text = (tag, value, className) => {
    const node = document.createElement(tag); node.textContent = value;
    if (className) node.className = className;
    return node;
  };
  const reportError = error => { $('error').textContent = error?.message || String(error); $('error').hidden = false; };
  async function api(path, options = {}) {
    const response = await fetch('/api/wechat-plus' + path, {
      cache: 'no-store', credentials: 'same-origin', ...options,
      headers: {'Content-Type': 'application/json', ...options.headers},
    });
    await window.AccountLifecycle?.checkResponse(response);
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) throw new Error('连接暂时中断，请稍后重试；已保存的内容不会丢失。');
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `请求未完成（${response.status}）`);
    return result;
  }
  function tab(name) {
    selectedTab = name;
    root.querySelectorAll('[data-wp-tab]').forEach(node => node.setAttribute('aria-selected', String(node.dataset.wpTab === name)));
    root.querySelectorAll('[data-wp-panel]').forEach(node => {node.hidden = node.dataset.wpPanel !== name;});
  }
  function updateBusy() {
    const busy = Boolean(active || pending);
    $('send').disabled = busy || !owner;
    $('input').disabled = busy || !owner;
    $('history').disabled = Boolean(pending);
    $('new').disabled = Boolean(pending);
    editor.readOnly = busy || Boolean(shownVersion);
    $('save').disabled = busy || !dirty || Boolean(shownVersion);
    root.querySelectorAll('.wp-topic,.wp-options button').forEach(button => {button.disabled = busy;});
    $('progress').hidden = !busy;
    if (active) {
      const seconds = Math.max(0, Math.floor((Date.now() - new Date(active.created_at).getTime()) / 1000));
      $('progress-text').textContent = `${active.progress || '正在处理'} · ${Math.floor(seconds / 60)}分${seconds % 60}秒`;
    } else if (pending) $('progress-text').textContent = '正在提交…';
    $('cancel').hidden = !active;
  }
  function drawReview(article) {
    const panel = root.querySelector('[data-wp-panel="review"]'); panel.replaceChildren();
    panel.append(text('h3', '复核与来源'));
    const report = article.quality_report || {};
    if (!Object.keys(report).length) panel.append(text('p', '还未复核。成稿后可告诉我“检查一下这篇文章”。'));
    const findings = report.hard_gate?.findings || [];
    if (Object.keys(report).length) {
      panel.append(text('p', report.hard_gate?.blocked ? '发现需要处理的问题，尚未通过交付检查。' : '本次复核已完成。此结果不代表平台流量或发布效果。'));
      findings.forEach(finding => panel.append(text('p', typeof finding === 'string' ? finding : (finding.message || finding.detail || finding.reason || JSON.stringify(finding)))));
      (article.reader_simulation || []).forEach(item => {
        panel.append(text('h4', item.role || item.reader || '读者视角'));
        panel.append(text('p', item.feedback || item.finding || item.suggestion || Object.values(item).filter(x => typeof x === 'string').join('；')));
      });
    }
    const pack = article.evidence_pack || {};
    panel.append(text('h4', '来源与限制'));
    (pack.limitations || []).forEach(item => panel.append(text('p', String(item))));
    const records = pack.sources?.records || [];
    if (!records.length) panel.append(text('p', '尚无可展示的公开来源。'));
    records.forEach(source => {
      const p = text('p', '');
      let url;
      try { url = new URL(source.url); } catch {}
      if (url?.protocol === 'https:') {
        const link = text('a', source.title || source.url); link.href = url.href;
        link.target = '_blank'; link.rel = 'noopener noreferrer'; p.append(link);
      } else p.append(text('span', source.title || source.source_id));
      p.append(text('small', ` · ${source.status === 'verified' ? '已核验' : '参考资料，需注意核验范围'}`));
      panel.append(p);
    });
  }
  function render() {
    const state = session?.state || {}, article = state.article_state || {};
    const nearBottom = messageRoot.scrollHeight - messageRoot.scrollTop - messageRoot.clientHeight < 80;
    const messages = state.messages || [];
    messageRoot.replaceChildren();
    if (!messages.length) messageRoot.append(text('p', '你好，把想写的方向或已有文章发给我。我们先找到值得讲的角度，再一起把它写清楚。', 'wp-message'));
    messages.forEach(message => {
      const node = text('p', message.content, 'wp-message'); node.dataset.role = message.role; messageRoot.append(node);
    });
    active = session?.turns?.find(turn => ['queued', 'running'].includes(turn.status)) || null;
    if (active) {
      const node = text('p', active.message, 'wp-message'); node.dataset.role = 'user'; messageRoot.append(node);
    }
    (state.choices || []).forEach((choice, index) => {
      const button = text('button', '', 'wp-topic'); button.type = 'button';
      button.append(text('strong', `${index + 1}. ${choice.title}`));
      const detail = choice.angle || choice.reason || choice.description;
      if (detail) button.append(text('small', detail));
      button.onclick = () => send(`我选择第${index + 1}个选题：${choice.title}`);
      messageRoot.append(button);
    });
    $('options').replaceChildren();
    (state.reply_options || []).forEach(option => {
      const button = text('button', option); button.type = 'button'; button.onclick = () => send(option); $('options').append(button);
    });
    const lastTurn = session?.turns?.[0];
    if (lastTurn?.status === 'failed') {
      $('error').textContent = lastTurn.error || '本次处理未完成，原稿已保留。'; $('error').hidden = false;
      const retry = text('button', '重试这次操作'); retry.type = 'button'; retry.onclick = () => send(lastTurn.message); $('options').append(retry);
    }
    if (!dirty && !shownVersion) editor.value = article.draft || '';
    $('empty').hidden = Boolean(editor.value);
    editor.hidden = !editor.value;
    $('copy').disabled = !editor.value;
    $('download').disabled = !editor.value;
    const versions = state.versions || [];
    $('versions').replaceChildren(new Option('当前正文', ''));
    [...versions].reverse().forEach(version => $('versions').append(new Option(`v${version.number} · ${version.reason}`, String(version.number))));
    $('versions').value = shownVersion;
    $('save-state').textContent = shownVersion ? '历史版本 · 只读' : dirty ? '有未保存修改' : article.draft ? '已保存' : '';
    drawReview(article);
    const nextPreview = article.formatted_output ? `${session.id}:${session.version}` : '';
    if (nextPreview !== previewKey) {
      previewKey = nextPreview;
      if (nextPreview) $('preview').src = `/api/wechat-plus/sessions/${session.id}/preview?v=${session.version}`;
      else $('preview').removeAttribute('src');
    }
    $('preview').hidden = !nextPreview;
    $('preview-empty').hidden = Boolean(nextPreview);
    updateBusy();
    if (nearBottom) messageRoot.scrollTop = messageRoot.scrollHeight;
  }
  async function list() {
    const sequence = epoch;
    const result = await api('/sessions');
    if (sequence !== epoch) return;
    $('history').replaceChildren(new Option('历史创作', ''));
    result.sessions.forEach(row => $('history').append(new Option(row.title, row.id)));
    $('history').value = session?.id || '';
    $('pricing').textContent = result.pricing;
  }
  async function poll() {
    if (!session || polling || !active) return;
    polling = true; const id = session.id, sequence = epoch;
    try {
      const result = await api(`/sessions/${id}`);
      if (sequence !== epoch || session?.id !== id) return;
      const changed = result.session.version !== session.version;
      session = result.session;
      render();
      if (!active && changed) {
        await list();
        if (session.state.last_action === 'format' && session.state.article_state?.formatted_output) tab('preview');
        if (session.state.last_action === 'review') tab('review');
      }
    } catch (error) { if (sequence === epoch) reportError(error); }
    finally { polling = false; }
  }
  async function open(id) {
    await save();
    const sequence = ++epoch;
    const result = await api(`/sessions/${encodeURIComponent(id)}`);
    if (sequence !== epoch) return;
    session = result.session; active = null; dirty = false; shownVersion = ''; previewKey = '';
    localStorage.setItem(key('active'), session.id);
    $('error').hidden = true; render(); $('history').value = session.id;
  }
  async function save() {
    if (saving) return saving;
    if (!dirty || !session || shownVersion) return;
    const id = session.id, sequence = epoch, value = editor.value;
    saving = (async () => {
      $('save-state').textContent = '正在保存…';
      const result = await api(`/sessions/${id}/draft`, {method: 'PUT', body: JSON.stringify({draft: value, version: session.version})});
      if (sequence !== epoch || session?.id !== id) return;
      session = result.session; dirty = editor.value !== value; render();
    })();
    try { await saving; } finally { saving = null; }
  }
  async function newSession() {
    await save(); ++epoch; session = null; active = null; dirty = false; shownVersion = '';
    pending = null; localStorage.removeItem(key('active')); previewKey = '';
    $('error').hidden = true; $('input').value = ''; editor.value = ''; tab('draft'); render();
  }
  async function send(value) {
    if (pending || active || !owner) return;
    const content = (value || $('input').value).trim(); if (!content) return;
    const sequence = epoch; $('error').hidden = true;
    try {
      await save();
      if (sequence !== epoch) return;
      if (!session) {
        const result = await api('/sessions', {method: 'POST', body: JSON.stringify({title: content.slice(0,40)})});
        if (sequence !== epoch) return;
        session = result.session; localStorage.setItem(key('active'), session.id);
      }
      // Store the exact request before publishing. A transport retry uses the
      // same idempotency key rather than creating another generation.
      pending = {session: session.id, message: content, version: session.version, idempotency_key: uuid()};
      localStorage.setItem(key('pending'), JSON.stringify(pending)); updateBusy();
      await publishPending();
    } catch (error) { if (sequence === epoch) reportError(error); }
  }
  async function publishPending() {
    if (!pending) return;
    const sequence = epoch, request = pending;
    try {
      const result = await api(`/sessions/${request.session}/messages`, {method:'POST', body:JSON.stringify(request)});
      if (sequence !== epoch) return;
      pending = null; localStorage.removeItem(key('pending'));
      $('input').value = ''; active = result.turn;
      session.turns = [result.turn, ...(session.turns || []).filter(turn => turn.id !== result.turn.id)];
      if (!['queued', 'running'].includes(result.turn.status)) {
        const latest = await api(`/sessions/${request.session}`);
        if (sequence !== epoch) return;
        session = latest.session;
      }
      render(); messageRoot.scrollTop = messageRoot.scrollHeight;
    } catch (error) {
      if (sequence !== epoch) return;
      reportError(error);
      // Keep the request recoverable while allowing an explicit retry.
      pending = request; updateBusy();
      const button = text('button', '重新连接，确认提交结果'); button.type='button';
      button.onclick = async () => { pending = request; updateBusy(); await publishPending(); };
      $('options').replaceChildren(button);
    }
  }
  async function ensureLoaded() {
    if (loading || root.hidden) return;
    const account = typeof currentAccount === 'undefined' ? null : currentAccount;
    if (!account?.id) { render(); return; }
    if (owner === account.id && timer) return;
    loading = true; owner = account.id;
    const expectedOwner = owner;
    try {
      await list();
      if (owner !== expectedOwner) return;
      const id = localStorage.getItem(key('active'));
      if (id) await open(id); else render();
      const stored = JSON.parse(localStorage.getItem(key('pending')) || 'null');
      if (stored && session?.id === stored.session) { pending = stored; updateBusy(); await publishPending(); }
      timer = setInterval(() => { updateBusy(); if (active) poll(); }, 2000);
    } catch(error) { reportError(error); }
    finally { loading = false; }
  }
  $('form').onsubmit = event => {event.preventDefault(); send();};
  $('input').onkeydown = event => {if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {event.preventDefault(); send();}};
  $('new').onclick = () => newSession().catch(reportError);
  $('history').onchange = () => {if ($('history').value) open($('history').value).catch(reportError);};
  $('cancel').onclick = async () => {
    if (!active || !session) return;
    try { await api(`/sessions/${session.id}/cancel/${active.id}`, {method:'POST'}); await poll(); }
    catch(error) {reportError(error);}
  };
  editor.oninput = () => {dirty = true; $('save-state').textContent = '有未保存修改'; updateBusy();};
  $('save').onclick = () => save().catch(reportError);
  $('versions').onchange = async () => {
    const targetVersion = $('versions').value;
    try {
      await save(); shownVersion = targetVersion;
      const version = session?.state.versions?.find(value => String(value.number) === shownVersion);
      editor.value = version ? version.draft : session?.state.article_state?.draft || '';
      render();
    } catch(error) {reportError(error);}
  };
  root.querySelectorAll('[data-wp-tab]').forEach(button => {button.onclick = () => tab(button.dataset.wpTab);});
  root.querySelector('[data-wp-prompt]').onclick = event => send(event.currentTarget.dataset.wpPrompt);
  $('import').onclick = () => {$('input').value = '请帮我修改下面这篇文章：\n\n'; $('input').focus();};
  $('copy').onclick = async () => {try {await navigator.clipboard.writeText(editor.value); $('save-state').textContent='已复制';} catch(error) {reportError(error);}};
  $('download').onclick = () => {
    const url = URL.createObjectURL(new Blob([editor.value], {type:'text/markdown;charset=utf-8'}));
    const link = document.createElement('a'); link.href=url; link.download='公众号文章.md'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault(); event.returnValue='';}});
  window.addEventListener('before-account-change', event => {if (dirty) event.detail.pending.push(save());});
  window.addEventListener('account-changed', () => {
    const next = typeof currentAccount === 'undefined' ? null : currentAccount?.id;
    if (owner === next) return;
    ++epoch; clearInterval(timer); timer=null; owner=null; session=null; active=null; pending=null; dirty=false; shownVersion=''; previewKey='';
    editor.value=''; $('preview').removeAttribute('src'); $('input').value=''; $('error').hidden=true;
    render(); ensureLoaded();
  });
  window.WechatPlus = {ensureLoaded};
  render();
})();
