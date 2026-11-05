/* Independent conversational workspace; no legacy creator state is reused. */
(() => {
  const root = document.querySelector('#wechat-plus');
  if (!root) return;
  const $ = name => root.querySelector(`[data-wp-${name}]`);
  let session = null, active = null, owner = null, epoch = 0, loading = false, submitting = false;
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
  const ARTICLE_START = '<!-- ========== ARTICLE HTML START ========== -->';
  const ARTICLE_END = '<!-- ========== ARTICLE HTML END ========== -->';
  const isDocument = /^\s*(?:<!doctype|<html[\s>])/i;
  /* 正式产物是纯正文片段（ARTICLE START/END + 全行内样式 section），直接交给
   * PublisherCopy.copyHtml，绝不走 DOMParser 往返：序列化会重写属性引号、自闭合
   * 标签、实体和注释。完整 HTML 文档只在兜存量会话的旧预览时才解析：删可执行节点、
   * 剥掉工具栏/手机框外壳、只留文章节点，并把 <head><style> 里的文章规则交给
   * PublisherCopy 压平成行内样式。 */
  function articleMarkup(source) {
    // 纯片段：严格空操作，原字符串直出，零序列化。
    if (!isDocument.test(source)) return source;

    const doc = new DOMParser().parseFromString(source, 'text/html');
    doc.querySelectorAll('script,iframe,object,embed').forEach(node => node.remove());
    // 完整文档的组件规则写在 <head><style>；页面级 reset 与预览外壳规则要剔除，
    // 否则压平后会把文章组件间距清掉。
    const css = [...doc.querySelectorAll('head style')].map(node => node.textContent || '').join('\n')
      .replace(/\/\*[\s\S]*?\*\//g, '');
    const rules = [];
    const re = /([^{}@]+)\{([^{}]*)\}/g;
    let match;
    while ((match = re.exec(css))) {
      const selector = match[1].trim(), body = match[2].trim();
      if (!selector || !body || selector.startsWith('@') || /::?|@/.test(selector)) continue;
      if (/^\s*(?:\*|html\b|body\b|:root\b)/i.test(selector)) continue;
      if (/\b(?:toolbar|phone-frame|back-to-top|toast|article-content|copy-article)\b/i.test(selector)) continue;
      rules.push(`${selector}{${body}}`);
    }

    // 存量完整页按可靠度依次剥壳：1) Skill 模板的正文边界注释（旧预览也带）；
    // 2) 已知正文容器 id；3) 都没有时删控件 + 拆掉手机框包装，只留正文节点。
    // 不猜「哪个 section 是手机框」，避免误删真实文章。
    let article = '';
    const fullBody = doc.body.innerHTML;
    const start = fullBody.indexOf(ARTICLE_START);
    const end = start < 0 ? -1 : fullBody.indexOf(ARTICLE_END, start + ARTICLE_START.length);
    if (start >= 0 && end > start) {
      article = fullBody.slice(start + ARTICLE_START.length, end).trim();
    } else {
      const container = doc.querySelector('#articleContent, #article-content, [data-wp-article]');
      if (container) {
        article = container.innerHTML;
      } else {
        doc.body.querySelectorAll('.toolbar, .toast, .back-to-top, #toast, #copyStatus, button')
          .forEach(node => node.remove());
        doc.body.querySelectorAll('.phone-frame, .article-content').forEach(wrapper => {
          const parent = wrapper.parentNode;
          if (!parent) return;  // 外壳可能已被上一步删除
          while (wrapper.firstChild) parent.insertBefore(wrapper.firstChild, wrapper);
          wrapper.remove();
        });
        article = doc.body.innerHTML;
      }
    }
    return (rules.length ? `<style>${rules.join('')}</style>` : '') + article;
  }
  // layout_capability.mode 的取值域：主路径 + 两次降级。
  // 必须显式映射：降级态仍可能带 module_count > 0，走 fallback 会被误标成「组件模式」，
  // 用户就看不出排版已经降级了。仲裁枚举是 skill-components / converter-pipeline /
  // legacy-template；服务端 render_trace 目前写的是短值 pipeline / legacy，两套都收。
  const MODE_LABELS = {
    'skill-native-dsl':'原生排版',
    'skill-components':'组件模式', 'converter-pipeline':'管线模式', 'legacy-template':'模板模式',
    pipeline:'管线模式', legacy:'模板模式',
    native:'组件模式', skill:'组件模式', 'skill-native':'组件模式', component:'组件模式',
    components:'组件模式', md2wechat:'组件模式',
    template:'模板模式', parameterized:'模板模式', fallback:'模板模式',
    fragment:'片段模式', snippet:'片段模式', inline:'片段模式',
    document:'完整页模式', full:'完整页模式',
  };
  const MODE_NOTES = {
    'skill-native-dsl':'（Skill 原生转换器渲染）',
    'converter-pipeline':'（组件主路径降级到 16 步 converter）',
    pipeline:'（组件主路径降级到 16 步 converter）',
    'legacy-template':'（二次降级到旧参数模板）',
    legacy:'（二次降级到旧参数模板）',
  };
  const modeKey = capability => String(capability?.mode || '').trim().toLowerCase();
  // 用 hasOwnProperty 取键：__proto__ / constructor 之类的未知值不能命中原型链，
  // 否则会把对象塞进标签里显示成 [object Object]。未知值一律走可读兜底。
  const lookup = (table, raw) => Object.prototype.hasOwnProperty.call(table, raw) ? table[raw] : '';
  const layoutMode = capability => {
    const label = lookup(MODE_LABELS, modeKey(capability));
    return label || ((Number(capability?.module_count) > 0 || Number(capability?.library_size) > 0)
      ? '组件模式' : '模板模式');
  };
  const modeNote = capability => lookup(MODE_NOTES, modeKey(capability));
  /* 模式 / 风格 / 组件能力放在主标签的兄弟节点：to_have_text 读的是主标签的
   * textContent，把详情做成子节点会把既有断言读成更长的字符串。 */
  let capabilityChipEl = null;
  function capabilityChip(themeLabel) {
    if (capabilityChipEl?.isConnected) return capabilityChipEl;
    const chip = document.createElement('span');
    chip.setAttribute('data-wp-layout-capability', '');
    chip.hidden = true;
    // 主标签是 white-space:nowrap，长文本会把窄屏工具栏顶出横向滚动；芯片允许换行。
    chip.style.cssText = 'display:none;font-size:10px;color:#537967;line-height:1.4;white-space:normal;max-width:100%;';
    themeLabel.after(chip);
    capabilityChipEl = chip;
    return chip;
  }
  const reportError = error => { $('error').textContent = error?.message || String(error); $('error').hidden = false; };
  async function api(path, options = {}) {
    const response = await fetch('/api/wechat-plus' + path, {
      cache: 'no-store', credentials: 'same-origin', signal: AbortSignal.timeout(30000), ...options,
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
    const busy = Boolean(active || pending || submitting);
    $('send').disabled = busy;
    $('input').disabled = busy;
    $('history').disabled = Boolean(pending || submitting);
    $('new').disabled = Boolean(pending || submitting);
    editor.readOnly = busy || Boolean(shownVersion);
    $('save').disabled = busy || !dirty || Boolean(shownVersion);
    root.querySelectorAll('.wp-topic,.wp-options button').forEach(button => {button.disabled = busy;});
    $('progress').hidden = !busy;
    if (active) {
      const seconds = Math.max(0, Math.floor((Date.now() - new Date(active.created_at).getTime()) / 1000));
      $('progress-text').textContent = `${active.progress || '正在处理'} · ${Math.floor(seconds / 60)}分${seconds % 60}秒`;
    } else if (pending || submitting) $('progress-text').textContent = '正在提交…';
    $('cancel').hidden = !active;
  }
  function drawReview(article, state) {
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
    const humanness = state?.humanness_report;
    if (humanness) {
      panel.append(text('h4', '人味评分'));
      if (humanness.available === false) {
        panel.append(text('p', '评分暂不可用，复核仍可继续。'));
      } else {
        const score = Number.isFinite(humanness.score) ? `${humanness.score}/100` : '暂无';
        const applied = humanness.applied ? '已按建议局部修订' : '仅给出修订建议';
        panel.append(text('p', `综合 ${score} · ${applied}`));
        const layers = humanness.layers || {};
        const layerText = [
          ['统计层', layers.statistical?.score],
          ['模式层', layers.pattern?.score],
          ['语义层', layers.llm?.score],
        ].filter(([, value]) => Number.isFinite(value))
          .map(([name, value]) => `${name} ${value}`).join(' · ');
        if (layerText) panel.append(text('p', layerText));
      }
      const plan = Array.isArray(humanness.repair_plan) ? humanness.repair_plan : [];
      if (plan.length) {
        panel.append(text('h4', '修订建议'));
        plan.forEach(item => panel.append(text('p',
          `${item.action || '修订'}${item.reason ? `：${item.reason}` : ''}`)));
      }
      if (humanness.revised_draft_rejected === 'too_much_rewrite') {
        panel.append(text('p', '模型改动过大，已保留原文，仅给出修订建议。'));
      } else if (humanness.revised_draft_rejected) {
        panel.append(text('p', '修订稿丢失了原文的数字、引用或链接，已保留原文。'));
      }
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
    const legacyImages = $('legacy-images');
    const legacyList = $('legacy-image-list');
    if (legacyImages && legacyList) {
      legacyList.replaceChildren();
      const images = Array.isArray(state.legacy_images) ? state.legacy_images : [];
      legacyImages.hidden = !images.length;
      images.forEach((item, index) => {
        if (!/^\/api\/(?:(?:workbench|qihaoshou)\/assets|storage)\//.test(item.url || '')) return;
        const link = document.createElement('a'); link.href = item.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        link.textContent = `查看历史配图 ${index + 1}`; legacyList.append(link);
      });
    }
    const nearBottom = messageRoot.scrollHeight - messageRoot.scrollTop - messageRoot.clientHeight < 80;
    const messages = state.messages || [];
    messageRoot.replaceChildren();
    if (!messages.length) messageRoot.append(text('p', '你好，把想写的方向或已有文章发给我。我们先找到值得讲的角度，再一起把它写清楚。', 'wp-message'));
    messages.forEach(message => {
      const node = text('p', message.content, 'wp-message'); node.dataset.role = message.role; messageRoot.append(node);
      if (message.role === 'assistant' && message.content.includes('贴图内容请前往「贴图号」')) { const link = text('a', '前往贴图号 →'); link.href = '/tie-tu'; node.append(' ', link); }
    });
    active = session?.turns?.find(turn => ['queued', 'running'].includes(turn.status)) || null;
    const lastTurn = session?.turns?.[0];
    const uncommitted = active || (['failed', 'cancelled'].includes(lastTurn?.status) ? lastTurn : null);
    if (uncommitted) {
      const node = text('p', uncommitted.message, 'wp-message'); node.dataset.role = 'user'; messageRoot.append(node);
      if (uncommitted.status === 'cancelled') messageRoot.append(text('p', '已取消，本次未更新正文。', 'wp-message'));
    }
    (state.choices || []).forEach((choice, index) => {
      const button = text('button', '', 'wp-topic'); button.type = 'button';
      button.append(text('strong', `${index + 1}. ${choice.title}`));
      const detail = choice.angle || choice.focus || choice.reason || choice.description;
      if (detail) button.append(text('small', detail));
      button.onclick = () => send(`我选择第${index + 1}个选题：${choice.title}`);
      messageRoot.append(button);
    });
    $('options').replaceChildren();
    const layoutOptions = ['write', 'format'].includes(state.last_action) && (state.reply_options || []).length;
    $('options').classList.toggle('wp-layout-options', Boolean(layoutOptions));
    if (layoutOptions) $('options').append(text('span', state.last_action === 'write' ? '选择排版风格，或在下方描述你的想法' : '继续调整排版', 'wp-layout-options-label'));
    (state.reply_options || []).forEach(option => {
      const button = text('button', option); button.type = 'button'; button.onclick = () => send(option); $('options').append(button);
    });
    if (lastTurn?.status === 'failed') {
      $('error').textContent = lastTurn.error || '本次处理未完成，原稿已保留。'; $('error').hidden = false;
      const retry = text('button', '继续上次未完成的处理'); retry.type = 'button';
      retry.onclick = async () => {
        try {
          await save();
          const response = await api(`/sessions/${session.id}/retry/${lastTurn.id}`, {method:'POST'});
          $('error').hidden = true; session.turns[0] = response.turn; active = response.turn; render();
        } catch(error) {reportError(error);}
      };
      $('options').append(retry);
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
    drawReview(article, state);
    const legacyPreview = Boolean(state.legacy_preview_html && article.draft === state.legacy_original_draft && !dirty);
    const nextPreview = article.formatted_output ? `${session.id}:${session.version}:current` : legacyPreview ? `${session.id}:${session.version}:legacy` : '';
    if (nextPreview !== previewKey) {
      previewKey = nextPreview;
      // chrome=1 只在 iframe 渲染时补 18px 横向留白；复制链路另行 fetch 不带该参数，
      // 保证粘进公众号的是逐字纯片段，不会多出一层内边距。
      if (nextPreview) $('preview').src = `/api/wechat-plus/sessions/${session.id}/${article.formatted_output ? 'preview' : 'legacy-preview'}?v=${session.version}&chrome=1`;
      else $('preview').removeAttribute('src');
    }
    $('preview').hidden = !nextPreview;
    $('preview-empty').hidden = Boolean(nextPreview);
    $('copy-html').disabled = !nextPreview || Boolean(shownVersion);
    const themeLabel = $('layout-theme');
    if (themeLabel) {
      const theme = state.layout_theme || {};
      const capability = state.layout_capability || {};
      const capabilityExists = Object.keys(capability).length > 0;
      const modules = (Array.isArray(theme.modules) ? theme.modules : []).map(item => item?.name || item);
      const moduleCount = Number.isFinite(capability.module_count) ? capability.module_count
        : Array.isArray(capability.modules) ? capability.modules.length : modules.length;
      const library = Number(capability.library_size) || 0;
      const styleOptions = Array.isArray(capability.style_options) ? capability.style_options : [];
      const styleName = capability.style || theme.style_name || theme.name || '';
      const mode = layoutMode(capability);
      // 兼容旧 state / 既有浏览器测试：没有 layout_capability 时，标签文字必须逐字
      // 保持「排版 · 简约清爽」，不追加后缀、不追加子节点。
      themeLabel.hidden = !nextPreview || (!theme.name && !styleName && !legacyPreview);
      themeLabel.textContent = styleName
        ? `排版 · ${styleName}${moduleCount ? ` · ${moduleCount} 模块` : ''}`
        : legacyPreview ? '历史排版' : '';
      themeLabel.title = [
        theme.name ? `基础主题 · ${theme.name}` : '',
        mode ? `排版模式 · ${mode}${modeNote(capability)}` : '',
        capability.style ? `视觉风格 · ${capability.style}` : '',
        styleOptions.length ? `可选风格 · ${styleOptions.join(' / ')}` : '',
        library ? `组件库 · ${library} 个` : '',
        modules.length ? `本版模块 · ${modules.join(' · ')}` : '',
        capability.variant ? `方案编号 · ${capability.variant}` : '',
        Number.isFinite(state.humanness_report?.score)
          ? `人味 · ${state.humanness_report.score}/100` : '',
      ].filter(Boolean).join('\n');
      const chip = capabilityExists ? capabilityChip(themeLabel) : null;
      if (chip) {
        const shown = Boolean(nextPreview);
        chip.hidden = !shown;
        chip.style.display = shown ? '' : 'none';
        chip.textContent = [
          mode,
          styleName ? `风格 · ${styleName}` : '',
          (moduleCount || library) ? `组件能力 · ${moduleCount} 模块${library ? ` / ${library} 组件库` : ''}` : '',
        ].filter(Boolean).join(' · ');
        chip.title = themeLabel.title;
      } else if (capabilityChipEl) {
        capabilityChipEl.hidden = true; capabilityChipEl.style.display = 'none';
      }
    }
    $('input').placeholder = article.draft ? '告诉我排版风格，例如：蓝色科技感、标题醒目…' : '想写的方向、已有素材，或者直接粘贴文章…';
    updateBusy();
    if (nearBottom) messageRoot.scrollTop = messageRoot.scrollHeight;
  }
  async function list() {
    const sequence = epoch;
    const result = await api('/sessions');
    if (sequence !== epoch) return;
    $('history').replaceChildren(new Option('历史创作', ''));
    $('history-warning').hidden = !result.legacy_migration_error;
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
      $('error').hidden = true;
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
    if (pending || active || submitting) return;
    const content = (value || $('input').value).trim(); if (!content) return;
    if (!owner) { $('input').value = content; showAuth(true); return; }
    const sequence = epoch; $('error').hidden = true; submitting = true; updateBusy();
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
    finally { submitting = false; updateBusy(); }
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
    if (!account?.id) {
      const params = new URLSearchParams(location.search), topic = params.get('topic');
      if (topic && !$('input').value) { $('input').value = topic; params.delete('topic'); params.delete('type'); history.replaceState(null, '', location.pathname + (params.size ? '?' + params : '') + location.hash); }
      render(); return;
    }
    if (owner === account.id && timer) return;
    loading = true; owner = account.id;
    const expectedOwner = owner;
    try {
      await list();
      if (owner !== expectedOwner) return;
      const id = localStorage.getItem(key('active'));
      const params = new URLSearchParams(location.search);
      const topic = params.get('topic');
      const legacyConversation = params.get('conversation');
      const requestedSession = params.get('session');
      if (topic) {
        render();
        $('input').value = topic;
        params.delete('topic'); params.delete('type');
        history.replaceState(null, '', location.pathname + (params.size ? '?' + params : '') + location.hash);
      } else if (legacyConversation) {
        const migrated = await api(`/legacy/conversation/${encodeURIComponent(legacyConversation)}`);
        await open(migrated.id);
        params.delete('conversation');
        history.replaceState(null, '', location.pathname + (params.size ? '?' + params : '') + location.hash);
      } else if (requestedSession) {
        await open(requestedSession);
        params.delete('session');
        history.replaceState(null, '', location.pathname + (params.size ? '?' + params : '') + location.hash);
      } else if (id) await open(id); else render();
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
  $('copy-html').onclick = async () => {
    try {
      await save();
      const state = session?.state || {}, article = state.article_state || {};
      const legacy = Boolean(state.legacy_preview_html && article.draft === state.legacy_original_draft && !dirty);
      if ((!article.formatted_output && !legacy) || shownVersion) throw new Error('正文已修改，请重新排版后复制。');
      const response = await fetch(`/api/wechat-plus/sessions/${session.id}/${article.formatted_output ? 'preview' : 'legacy-preview'}`, {credentials:'same-origin', cache:'no-store', signal:AbortSignal.timeout(30000)});
      await window.AccountLifecycle?.checkResponse(response);
      if (!response.ok || !response.headers.get('content-type')?.includes('text/html')) throw new Error('读取排版未完成，请稍后重试。');
      const html = await response.text();
      // 正式产物是「纯正文片段」（全行内样式、ARTICLE START/END 边界）：
      // articleMarkup 原样返回字符串，不做 DOMParser 往返。兼容层只处理存量旧文件 /
      // 未来变体回退到的完整 HTML 文档：删可执行节点、剥工具栏与手机框、压平 <style>。
      // 统一走 PublisherCopy.copyHtml：压平行内样式 → 写入 → 回读校验 → 失败降级。
      // 公众号后台只认行内 style，<style> 块和 class 一点都不留。
      const report = await window.PublisherCopy.copyHtml(articleMarkup(html));
      $('save-state').textContent = report?.inlined
        ? '排版已复制（已转为行内样式），可粘贴到公众号编辑器'
        : `排版已复制（${report?.styleCount || 0} 处样式），可粘贴到公众号编辑器`;
    } catch(error) {reportError(error);}
  };
  $('download').onclick = () => {
    const url = URL.createObjectURL(new Blob([editor.value], {type:'text/markdown;charset=utf-8'}));
    const link = document.createElement('a'); link.href=url; link.download='公众号文章.md'; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault(); event.returnValue='';}});
  window.addEventListener('before-account-change', event => {if (dirty) event.detail.pending.push(save());});
  window.addEventListener('account-changed', () => {
    const next = typeof currentAccount === 'undefined' ? null : currentAccount?.id || null;
    if (owner === next) return;
    const guestInput = !owner && next ? $('input').value : '';
    ++epoch; clearInterval(timer); timer=null; owner=null; session=null; active=null; pending=null; submitting=false; dirty=false; shownVersion=''; previewKey='';
    editor.value=''; $('preview').removeAttribute('src'); $('input').value=guestInput; $('error').hidden=true;
    render(); ensureLoaded();
  });
  window.WechatPlus = {ensureLoaded};
  render();
})();
