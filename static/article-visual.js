/* 文章配图工具页逻辑：拆解 → 先出封面 → 确认后批量出剩余 */
(function () {
  "use strict";

  const FORM_LABEL = {
    cover: "封面",
    data: "数据卡",
    timeline: "时间线",
    layers: "结构拆解",
    compare: "对比",
    clients: "客户版图",
    quote: "金句",
  };

  const state = { job: null, activeId: null, busy: false, stamp: 0, coverStyle: "compare", tab: "plan" };
  const COVER_STYLES = [
    { id: "compare", label: "对比式", hint: "问题 vs 解决，冲突最强" },
    { id: "number", label: "数字式", hint: "大数字砸脸，缩略图最清楚" },
    { id: "object", label: "主题主体式", hint: "根据文章内容展示人物、产品或场景" },
  ];

  const $ = (id) => document.getElementById(id);
  const els = {
    url: $("av-url"),
    sourceText: $("av-source-text"),
    sourceTitle: $("av-text-title"),
    analyze: $("av-analyze"),
    hint: $("av-hint"),
    stickerLink: $("av-go-sticker-extract"),
    articlePanel: $("av-article-panel"),
    empty: $("av-empty"),
    plan: $("av-plan"),
    planTitle: $("av-plan-title"),
    tabs: $("av-tabs"),
    summary: $("av-summary"),
    title: $("av-article-title"),
    meta: $("av-article-meta"),
    thesis: $("av-thesis"),
    reset: $("av-reset"),
    list: $("av-slot-list"),
    angles: $("av-angles"),
    planContent: $("av-plan-content"),
    count: $("av-count"),
    stageTitle: $("av-stage-title"),
    stageStatus: $("av-stage-status"),
    preview: $("av-preview"),
    previewImg: $("av-preview-img"),
    previewEmpty: $("av-preview-empty"),
    actions: $("av-actions"),
    coverStyles: $("av-cover-styles"),
    editor: $("av-editor"),
    note: $("av-note"),
    galleryPanel: $("av-gallery-panel"),
    gallery: $("av-gallery"),
    publication: $("av-publication"),
    downloadAll: $("av-download-all"),
    toast: $("av-toast"),
  };

  function toast(message, ms = 2600) {
    els.toast.textContent = message;
    els.toast.hidden = false;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { els.toast.hidden = true; }, ms);
  }

  // 等待期间每秒刷新一次已用时间，避免「拆解中…」看起来像卡死。
  let ticker = null;
  function startTicker(element, prefix) {
    const started = Date.now();
    element.textContent = `${prefix} 0s`;
    clearInterval(ticker);
    ticker = setInterval(() => {
      element.textContent = `${prefix} ${Math.floor((Date.now() - started) / 1000)}s`;
    }, 500);
    return () => {
      clearInterval(ticker);
      ticker = null;
      return Date.now() - started;
    };
  }

  function seconds(ms) {
    if (!ms) return "";
    return `${(ms / 1000).toFixed(1)}s`;
  }

  async function api(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeoutMs || 180000);
    let response;
    try {
      response = await fetch(path, {
        credentials: "same-origin",
        headers: options.body ? { "Content-Type": "application/json" } : undefined,
        signal: controller.signal,
        ...options,
      });
    } catch (error) {
      if (error.name === "AbortError") {
        throw new Error("请求超时了，服务端可能还在跑；稍后刷新页面看结果，或重试一次");
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
    let data = null;
    try { data = await response.json(); } catch (_) { /* ignore */ }
    if (!response.ok) {
      if (response.status === 401) {
        if (typeof showAuth === 'function') showAuth(true);
        else window.location.href = "/?register=1";
        throw new Error("请先登录");
      }
      const retries = options._retryCount || 0;
      if (response.status === 503 && retries < 3) {
        // 503 是网关还没把请求交给应用（部署切换容器的几秒），重试不会重复扣费。
        // 502 有可能是请求已进应用后被重启打断，不自动重试，避免double charge。
        const delay = [2000, 4000, 6000][retries];
        await new Promise((resolve) => setTimeout(resolve, delay));
        return api(path, { ...options, _retryCount: retries + 1 });
      }
      if ([502, 503, 504].includes(response.status)) {
        throw new Error(`服务正在更新或重启（${response.status}），等 10 秒再点一次；不是你链接的问题`);
      }
      const detail = (data && (data.detail || data.message)) || `请求失败（${response.status}）`;
      const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail)); error.status = response.status; throw error;
    }
    return data;
  }

  function slotSummary(slot) {
    const items = slot.items || [];
    if (slot.form === "timeline") {
      return items.map((i) => `${i.year || ""} ${i.text || ""}`.trim()).join(" → ");
    }
    if (slot.form === "data") {
      return items.map((i) => `${i.value || ""} ${i.label || ""}`.trim()).join(" / ");
    }
    if (slot.form === "layers") {
      return items.map((i) => `${i.name || ""}${i.note ? "：" + i.note : ""}`).join(" / ");
    }
    if (slot.form === "compare") {
      return items.map((i) => i.side || "").filter(Boolean).join(" vs ");
    }
    if (slot.form === "clients") {
      return items.map((i) => (typeof i === "string" ? i : i.name || "")).filter(Boolean).join(" / ");
    }
    if (slot.form === "cover") {
      return [slot.kicker, slot.headline, ...(items || [])].filter(Boolean).join(" · ");
    }
    return slot.headline || "";
  }

  function imageUrl(slotId) {
    const entry = state.job && state.job.images && state.job.images[slotId];
    if (!entry) return "";
    return `/api/article-visual/${state.job.id}/images/${entry.file}?v=${state.stamp}`;
  }

  function setTab(tab) {
    state.tab = tab;
    if (els.tabs) {
      els.tabs.querySelectorAll("[data-tab]").forEach((button) => {
        button.classList.toggle("is-active", button.dataset.tab === tab);
      });
    }
    ["plan", "cover", "gallery"].forEach((name) => {
      const panel = $("av-tab-" + name);
      if (panel) panel.hidden = name !== tab;
    });
    if (tab === "gallery") renderGallery();
  }

  function render() {
    if (!state.job) return;
    const slots = state.job.slots;
    const done = slots.filter((s) => s.status === "done").length;

    els.title.textContent = state.job.article.title || "未命名文章";
    els.meta.textContent = [state.job.article.source_kind === "user_text" ? "用户提供正文 · 未独立核实" : "", state.job.article.account, state.job.article.publish_time, `${state.job.article.chars} 字`]
      .filter(Boolean).join(" · ");
    els.thesis.textContent = state.job.plan.thesis ? `核心：${state.job.plan.thesis}` : "";
    els.planTitle.textContent = `这篇文章可以拆成 ${slots.length} 张图`;
    els.summary.innerHTML = [
      `<span>拆解总计 <b>${state.job.elapsed_ms ? seconds(state.job.elapsed_ms) : "—"}</b></span>`,
      `<span>图位 <b>${slots.length} 张</b></span>`,
      `<span>已生成 <b>${done} 张</b></span>`,
      `<span>积分 <b>2 / 张</b></span>`,
    ].join("");
    els.empty.hidden = true;
    els.plan.hidden = false;

    renderAngles();
    els.list.innerHTML = "";
    slots.forEach((slot) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "av-slot-card" + (slot.form === "cover" ? " is-cover" : "")
        + (slot.id === state.activeId ? " is-active" : "")
        + (slot.status === "done" ? " is-done" : "");
      card.dataset.id = slot.id;

      const thumb = document.createElement("div");
      thumb.className = "av-slot-thumb";
      thumb.textContent = (slot.headline || "").slice(0, 12);

      const info = document.createElement("div");
      info.className = "av-slot-info";
      const cap = document.createElement("div");
      cap.className = "av-slot-cap";
      cap.innerHTML = `<span>${FORM_LABEL[slot.form] || slot.form}</span><em>${slot.status === "done" ? "已生成" : "待生成"}</em>`;
      const h3 = document.createElement("h3");
      h3.textContent = slot.headline || "未命名图位";
      const p = document.createElement("p");
      p.textContent = slot.detail || slotSummary(slot) || slot.brief || "";
      if (slot.source_quote) p.title = `原文依据：${slot.source_quote}`;
      const chips = document.createElement("div");
      chips.className = "av-chips";
      (slot.facts || []).slice(0, 3).forEach((fact) => {
        const chip = document.createElement("span");
        chip.textContent = fact;
        chips.appendChild(chip);
      });
      const evidence = document.createElement("span");
      evidence.className = "av-evidence";
      evidence.textContent = slot.source_quote ? `原文依据：${slot.source_quote}` : "";
      info.append(cap, h3, p, chips, evidence);
      card.append(thumb, info);
      card.addEventListener("click", () => {
        if (state.busy) return;
        state.activeId = slot.id;
        render();
        setTab("cover");
      });
      els.list.appendChild(card);
    });

    const active = slots.find((s) => s.id === state.activeId) || slots[0];
    state.activeId = active.id;
    renderStage(active, slots);
  }

  function renderAngles() {
    const plan = state.job.plan || {};
    const choices = plan.alternatives || [];
    const selected = plan.selected_angle;
    els.angles.innerHTML = "";
    els.planContent.hidden = choices.length > 0 && selected == null;
    if (!choices.length) return;
    const title = document.createElement("h2");
    title.textContent = selected == null ? "选择传播角度" : "已选传播角度";
    const help = document.createElement("p");
    help.textContent = "先确定封面方向，图位会围绕这个方向展开。";
    els.angles.append(title, help);
    const list = document.createElement("div");
    list.className = "av-angle-list";
    choices.forEach((choice, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "av-angle-option" + (selected === index ? " is-active" : "");
      button.disabled = state.busy;
      const label = document.createElement("b");
      label.textContent = `${index === 0 ? "推荐 · " : ""}${choice.angle_label || `方向 ${index + 1}`}`;
      const headline = document.createElement("strong");
      headline.textContent = choice.slots?.[0]?.headline || "封面方向";
      const reason = document.createElement("span");
      reason.textContent = choice.angle_reason || "基于文章内容提炼";

      const quote = document.createElement("small");
      quote.textContent = `原文依据：${choice.slots?.[0]?.source_quote || "暂无"}`;
      button.append(label, headline, reason, quote);
      if (choice.review_notice) { const warning = document.createElement("span"); warning.className = "av-review-warning"; warning.textContent = choice.review_notice; button.appendChild(warning); }
      button.addEventListener("click", async () => {
        if (state.busy) return;
        state.busy = true;
        renderAngles();
        try {
          state.job = await api(`/api/article-visual/${state.job.id}/angle`, {method:"POST", body:JSON.stringify({index})});
          state.activeId = state.job.slots[0]?.id;
          history.replaceState(null, "", `/article-visual?job=${encodeURIComponent(state.job.id)}`);
        } catch (error) { toast(error.message, 4000); }
        finally { state.busy = false; render(); }
      });
      list.appendChild(button);
    });
    els.angles.appendChild(list);
    if (Object.keys(state.job.images || {}).length > 0) {
      const note = document.createElement("p");
      note.textContent = "切换其他方向会创建新的图位方案，已生成的图片会保留在原方案中。";
      els.angles.appendChild(note);
    }
    if (selected != null) {
      const next = document.createElement("button");
      next.type = "button";
      next.className = "av-btn av-btn-primary";
      next.textContent = "查看封面并生成 →";
      next.addEventListener("click", () => { state.activeId = state.job.slots[0]?.id; render(); setTab("cover"); });
      els.angles.appendChild(next);
    }
  }

  function setStatus(text, kind) {
    els.stageStatus.textContent = text;
    els.stageStatus.className = "av-stage-status" + (kind ? ` is-${kind}` : "");
  }

  function renderCoverStyles(slot) {
    if (!els.coverStyles) return;
    if (slot.form !== "cover") {
      els.coverStyles.hidden = true;
      els.coverStyles.innerHTML = "";
      return;
    }
    els.coverStyles.hidden = false;
    els.coverStyles.innerHTML = "";
    const label = document.createElement("span");
    label.className = "av-cover-styles-label";
    label.textContent = "封面样式";
    els.coverStyles.appendChild(label);
    COVER_STYLES.forEach((style) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "av-style-chip" + (state.coverStyle === style.id ? " is-active" : "");
      button.title = style.hint;
      button.textContent = style.label;
      button.setAttribute("aria-pressed", String(state.coverStyle === style.id));
      button.addEventListener("click", () => {
        state.coverStyle = style.id;
        renderCoverStyles(slot);
        els.note.textContent = `已选择「${style.label}」：${style.hint}。${imageUrl(slot.id) ? "当前仍显示上次成图，点击“重做这张”应用新样式。" : "点击“生成封面”应用此样式。"}`;
      });
      els.coverStyles.appendChild(button);
    });
  }

  function renderStage(slot, slots) {
    els.stageTitle.textContent = `${FORM_LABEL[slot.form] || "图位"} · ${slot.headline || ""}`.trim();
    renderCoverStyles(slot);
    const url = imageUrl(slot.id);
    if (url) {
      els.previewImg.src = url;
      els.previewImg.hidden = false;
      els.previewEmpty.hidden = true;
      setStatus(slot.elapsed_ms ? `已生成 · ${seconds(slot.elapsed_ms)}` : "已生成", "ok");
    } else {
      els.previewImg.hidden = true;
      els.previewImg.removeAttribute("src");
      els.previewEmpty.hidden = false;
      setStatus("等待生成");
    }

    els.editor.innerHTML = "";
    const editorLabel = document.createElement("label");
    editorLabel.textContent = "图上标题（改完点「重做这张」生效）";
    const editorInput = document.createElement("input");
    editorInput.type = "text";
    editorInput.maxLength = 24;
    editorInput.value = slot.headline || "";
    editorInput.addEventListener("input", () => {
      slot.headline = editorInput.value.slice(0, 24);
    });
    els.editor.appendChild(editorLabel);
    els.editor.appendChild(editorInput);

    els.actions.innerHTML = "";
    const remaining = slots.filter((s) => s.status !== "done" && s.form !== "cover").length;

    if (!url) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "av-btn av-btn-primary";
      btn.textContent = slot.form === "cover" ? "生成封面" : "生成这张";
      btn.disabled = state.busy;
      btn.addEventListener("click", () => generate(slot.id));
      els.actions.appendChild(btn);
      els.note.textContent = slot.form === "cover"
        ? "先只出封面。你看满意了，再生成剩下的图。"
        : "单张生成约 40–60 秒。";
      return;
    }

    if (slot.form === "cover") {
      const go = document.createElement("button");
      go.type = "button";
      go.className = "av-btn av-btn-primary";
      go.textContent = remaining ? `满意，继续生成剩余 ${remaining} 张` : "全部完成";
      go.disabled = state.busy || !remaining;
      go.addEventListener("click", async () => {
        if (state.busy) return;
        go.disabled = true;
        try {
          await api(`/api/article-visual/${state.job.id}/confirm-cover`, {method:"POST"});
          state.job.cover_confirmed = true;
          await generateRemaining();
        } catch (error) { toast(error.message, 4000); go.disabled = false; }
      });
      els.actions.appendChild(go);
    }

    const again = document.createElement("button");
    again.type = "button";
    again.className = "av-btn";
    again.textContent = "重做这张";
    again.disabled = state.busy;
    again.addEventListener("click", () => generate(slot.id, true));
    els.actions.appendChild(again);

    const download = document.createElement("a");
    download.className = "av-btn av-btn-ghost";
    download.href = url;
    download.download = `${slot.id}.png`;
    download.textContent = "下载";
    els.actions.appendChild(download);

    els.note.textContent = slot.form === "cover"
      ? "不满意就「重做这张」，不用重新拆解。"
      : "";
  }

  async function loadJob(jobId) {
    const job = await api(`/api/article-visual/${jobId}`);
    state.job = job;
    state.activeId = job.slots[0] ? job.slots[0].id : null;
    els.articlePanel.hidden = false;
    render();
    renderGallery();
    setTab("plan");
  }

  async function analyze() {
    const url = els.url.value.trim();
    const sourceText = els.sourceText.value.trim();
    const sourceTitle = els.sourceTitle.value.trim();
    let pending = null; try { pending = JSON.parse(localStorage.getItem(`article-visual-pending:${currentAccount?.id}`) || 'null'); } catch {}
    if (!url && !sourceText && !pending?.resumeFrom) { els.url.focus(); els.hint.textContent = '请填写链接，或展开下方输入文章正文。'; return; }
    if (sourceText && sourceText.length < 40) { els.hint.textContent = '粘贴的正文少于 40 字，请补充完整正文。'; els.sourceText.focus(); return; }
    await initialAccountReady;
    if (!currentAccount?.id) { showAuth(true); return; }
    if (state.busy) return;
    state.job = null;
    state.activeId = null;
    els.articlePanel.hidden = true;
    els.plan.hidden = true;
    els.empty.hidden = false;
    history.replaceState(null, "", "/article-visual");
    state.busy = true;
    els.url.readOnly = true; els.sourceText.readOnly = true; els.sourceTitle.readOnly = true;
    els.analyze.disabled = true;
    els.analyze.textContent = "拆解中…";
    els.hint.classList.remove("is-error");
    els.stickerLink.hidden = true;
    els.hint.textContent = '正在提交拆解任务…';
    try {
      await initialAccountReady;
      const owner = currentAccount?.id;
      if (!owner) throw new Error('请先登录');
      let record = null; try { record = JSON.parse(localStorage.getItem(`article-visual-pending:${owner}`) || 'null'); } catch {}
      if (record && record.url !== url) throw new Error('上一项拆解仍待确认，请先等待或刷新页面恢复');
      record = record || {url, key:newIdempotencyKey(), owner, manual:!!sourceText};
      localStorage.setItem(`article-visual-pending:${owner}`, JSON.stringify(record));
      const job = await waitForPlan(record, {sourceText, sourceTitle});
      state.job = job;
      state.activeId = job.slots[0] ? job.slots[0].id : null;
      els.articlePanel.hidden = false;
      history.replaceState(null, "", `/article-visual?job=${job.id}`);
      render();
      setTab("plan");
      const cost = job.elapsed_ms ? seconds(job.elapsed_ms) : "";
      els.hint.textContent = `拆解完成${cost ? `，用时 ${cost}` : ""}。可选择方向：${job.plan?.alternatives?.length || 0} 个，请留意各方向的核对提示，请选择传播角度。`;
    } catch (error) {
      els.hint.classList.add("is-error");
      els.hint.textContent = error.message;
      if (error.message.includes("正文") || error.message.includes("读取文章")) $("av-text-entry").open = true;
      els.stickerLink.hidden = !error.message.startsWith('这是贴图号图文');
      if (!state.job) {
        els.articlePanel.hidden = true;
        els.empty.hidden = false;
        els.plan.hidden = true;
      }
    } finally {
      state.busy = false;
      els.url.readOnly = false; els.sourceText.readOnly = false; els.sourceTitle.readOnly = false;
      els.analyze.disabled = false;
      els.analyze.textContent = "拆解文章";
      if (state.job) renderAngles();
    }
  }

  async function waitForPlan(record, source = {}) {
    const storageKey = `article-visual-pending:${record.owner}`;
    if (!record.id) {
      if (!record.resumeFrom && !source.sourceText && !record.preflightId) {
        els.hint.textContent = '正在检查文章链接与内容类型，本步骤不扣积分…';
        try {
          const checked = await api('/api/article-visual/preflight', {method:'POST', body:JSON.stringify({url:record.url})});
          if (!checked.preflight_id) throw new Error('文章预检查未返回有效结果，本次未扣积分。');
          if (currentAccount?.id !== record.owner) throw new Error('账号已切换，请返回后重新检查文章。');
          record.preflightId = checked.preflight_id;
          localStorage.setItem(storageKey, JSON.stringify(record));
        } catch (error) { localStorage.removeItem(storageKey); throw error; }
      }
      let created;
      try { created = await api('/api/article-visual/tasks/start', {method:'POST',body:JSON.stringify({url:record.url,idempotency_key:record.key,resume_task_id:record.resumeFrom || null,preflight_id:record.preflightId || null,source_text:source.sourceText || '',source_title:source.sourceTitle || ''})}); }
      catch (error) { if (error.status >= 400 && error.status < 500 && error.status !== 429) localStorage.removeItem(storageKey); throw error; }
      if (currentAccount?.id !== record.owner) throw new Error('账号已切换，任务仍在后台执行');
      record.id = created.job.id; localStorage.setItem(storageKey, JSON.stringify(record));
    }
    const labels = {extracting:'正在读取文章',planning:'正在生成传播方向',retrying:'服务响应异常，正在自动重试',checking:'正在核对原文',repairing:'正在修复方案',reviewing:'正在进行事实复核'};
    while (currentAccount?.id === record.owner) {
      const data = await api(`/api/article-visual/tasks/${encodeURIComponent(record.id)}`);
      const job = data.job, stage = job.progress?.stage;
      els.hint.textContent = (labels[stage] || '任务排队中') + (job.progress?.total ? ` · ${job.progress.current}/${job.progress.total}` : '');
      if (job.status === 'succeeded') { localStorage.removeItem(storageKey); localStorage.removeItem(`article-visual-review:${record.owner}`); $('av-resume-review').hidden = true; return job.result; }
      if (['failed','canceled'].includes(job.status)) {
        localStorage.removeItem(storageKey);
        if (job.resume_available) { localStorage.setItem(`article-visual-review:${record.owner}`, JSON.stringify({id:job.id,url:record.url,owner:record.owner})); $('av-resume-review').hidden = false; }
        const refund = job.billing_status === 'refunded' ? '积分已退回。' : job.billing_status === 'reserved' ? '积分退款处理中，请稍后查看。' : '';
        const detail = (job.error || '拆解服务未完成，请稍后重试。').replace(/本次(?:失败)?积分(?:将自动退回|已退回|会退还积分)[；。，]?/g, '').replace(/失败积分将自动退回[；。，]?/g, '');
        throw new Error(`${detail} ${refund} 任务编号：${job.id}`.trim());
      }
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    throw new Error('账号已切换，任务仍在后台执行');
  }

  async function resumePending() {
    await initialAccountReady;
    const owner = currentAccount?.id; if (!owner || state.busy) return;
    try { $('av-resume-review').hidden = !JSON.parse(localStorage.getItem(`article-visual-review:${owner}`) || 'null'); } catch { $('av-resume-review').hidden = true; }
    let record; try { record = JSON.parse(localStorage.getItem(`article-visual-pending:${owner}`) || 'null'); } catch { return; }
    if (record && !record.id && record.manual && !record.resumeFrom) {
      try {
        const recent = await api('/api/article-visual/tasks/recent');
        if (currentAccount?.id !== owner) return;
        const existing = (recent.jobs || []).find(job => job.client_key === record.key);
        if (existing) { record.id = existing.id; localStorage.setItem(`article-visual-pending:${owner}`, JSON.stringify(record)); }
        else {
          localStorage.removeItem(`article-visual-pending:${owner}`);
          els.hint.textContent = '未找到上次手动正文的任务，请重新粘贴正文后提交；已提交的任务可在历史记录中查看。';
          $('av-text-entry').open = true;
          return;
        }
      } catch { els.hint.textContent = '暂时无法确认上次任务状态，请稍后刷新重试，避免重复提交。'; return; }
    }
    if (!record) {
      try {
        const recent = await api('/api/article-visual/tasks/recent');
        if (currentAccount?.id !== owner || state.busy) return;
        const active = (recent.jobs || []).find(job => ['queued', 'running'].includes(job.status) && (job.url || job.manual_source));
        const review = (recent.jobs || []).find(job => job.resume_available && (job.url || job.manual_source));
        if (review && !active) { localStorage.setItem(`article-visual-review:${owner}`, JSON.stringify({id:review.id,url:review.url,owner})); $('av-resume-review').hidden = false; }
        if (active) { record = {id:active.id,url:active.url,owner}; localStorage.setItem(`article-visual-pending:${owner}`, JSON.stringify(record)); }
      } catch { /* 网络不可用时保留现有页面，稍后可重试 */ }
    }
    if (!record || record.owner !== owner) return;
    state.busy = true; els.analyze.disabled = true; els.url.readOnly = true; els.url.value = record.url || '';
    els.hint.textContent = '正在恢复上次拆解任务…';
    try {
      const job = await waitForPlan(record);
      state.job = job; state.activeId = job.slots[0]?.id || null; els.articlePanel.hidden = false;
      history.replaceState(null, '', `/article-visual?job=${encodeURIComponent(job.id)}`);
      render(); setTab('plan'); els.hint.textContent = `已恢复拆解结果，可选择 ${job.plan?.alternatives?.length || 0} 个方向，请留意各方向的核对提示。`;
    } catch (error) { els.hint.textContent = error.message; els.hint.classList.add('is-error'); els.stickerLink.hidden = !error.message.startsWith('这是贴图号图文'); }
    finally { state.busy = false; els.analyze.disabled = false; els.url.readOnly = false; if (state.job) renderAngles(); }
  }

  $('av-resume-review').addEventListener('click', () => {
    const owner = currentAccount?.id; if (!owner || state.busy) return;
    let saved; try { saved = JSON.parse(localStorage.getItem(`article-visual-review:${owner}`) || 'null'); } catch { return; }
    if (!saved || saved.owner !== owner) return;
    els.url.value = saved.url;
    localStorage.setItem(`article-visual-pending:${owner}`, JSON.stringify({url:saved.url,key:newIdempotencyKey(),owner,resumeFrom:saved.id}));
    analyze();
  });

  async function generate(slotId, force) {
    if (state.busy || !state.job) return;
    state.busy = true;
    const slot = state.job.slots.find((s) => s.id === slotId);
    const stopTicker = startTicker(els.stageStatus, force ? "重做中，已用" : "生成中，已用");
    els.actions.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      const result = await api("/api/article-visual/generate", {
        method: "POST",
        body: JSON.stringify({
          job_id: state.job.id,
          slot_id: slotId,
          headline: slot ? slot.headline : undefined,
          cover_style: slot && slot.form === "cover" ? state.coverStyle : undefined,
        }),
      });
      state.job.images[slotId] = { file: result.url.split("/").pop().split("?")[0] };
      state.job.publication = null;
      const target = state.job.slots.find((s) => s.id === slotId);
      if (target) {
        target.status = "done";
        target.elapsed_ms = result.elapsed_ms;
      }
      state.stamp = Date.now();
      toast(force ? "这张已重做" : "生成完成");
      stopTicker();
      state.busy = false;
      render();
      renderGallery();
    } catch (error) {
      stopTicker();
      state.busy = false;
      setStatus("失败，可重试", "busy");
      els.note.textContent = error.message;
      toast(error.message, 4000);
      renderStage(slot || { form: "data", headline: "" }, state.job.slots);
    }
  }

  async function generateRemaining() {
    if (state.busy || !state.job) return;
    const pending = state.job.slots.filter((s) => s.status !== "done" && s.form !== "cover");
    if (!pending.length) return;
    state.busy = true;
    const batchStarted = Date.now();
    for (let index = 0; index < pending.length; index += 1) {
      const slot = pending[index];
      state.activeId = slot.id;
      render();
      setStatus(`正在生成 ${index + 1}/${pending.length}：${slot.headline}`, "busy");
      try {
        const result = await api("/api/article-visual/generate", {
          method: "POST",
          body: JSON.stringify({ job_id: state.job.id, slot_id: slot.id, headline: slot.headline }),
        });
        state.job.images[slot.id] = { file: result.url.split("/").pop().split("?")[0] };
        state.job.publication = null;
        slot.status = "done";
        slot.elapsed_ms = result.elapsed_ms;
        state.stamp = Date.now();
        render();
      } catch (error) {
        state.busy = false;
        toast(`「${slot.headline}」失败：${error.message}`, 4000);
        render();
        renderGallery();
        return;
      }
    }
    state.busy = false;
    const total = ((Date.now() - batchStarted) / 1000).toFixed(1);
    setStatus(`全部生成完成 · 共 ${total}s`, "ok");
    render();
    renderGallery();
    toast(`一套图出完了，共用 ${total} 秒`);
  }

  function renderGallery() {
    if (!state.job) return;
    const done = state.job.slots.filter((s) => state.job.images[s.id]);
    els.gallery.innerHTML = "";
    els.publication.replaceChildren();
    if (!done.length) {
      els.gallery.innerHTML = '<p class="av-gallery-empty">还没有成图。先在「图位方案」里选一张，生成封面后再回来。</p>';
      return;
    }
    done.forEach((slot) => {
      const card = document.createElement("div");
      card.className = "av-card";
      const link = document.createElement("a");
      link.href = imageUrl(slot.id);
      link.download = `${slot.id}.png`;
      const img = document.createElement("img");
      img.src = imageUrl(slot.id);
      img.alt = slot.headline || slot.id;
      link.appendChild(img);
      const foot = document.createElement("div");
      foot.className = "av-card-foot";
      foot.innerHTML = `<span>${FORM_LABEL[slot.form] || ""}</span><span>${slot.headline || ""}</span>`;
      card.appendChild(link);
      card.appendChild(foot);
      els.gallery.appendChild(card);
    });
    els.publication.append(window.RemixPublication.render(state.job, {endpoint: `/api/article-visual/${encodeURIComponent(state.job.id)}/publication`}));
  }

  els.downloadAll.addEventListener("click", (event) => {
    event.preventDefault();
    if (!state.job) return;
    const done = state.job.slots.filter((s) => state.job.images[s.id]);
    done.forEach((slot, index) => {
      setTimeout(() => {
        const a = document.createElement("a");
        a.href = imageUrl(slot.id);
        a.download = `${slot.id}.png`;
        document.body.appendChild(a);
        a.click();
        a.remove();
      }, index * 400);
    });
  });

  els.reset.addEventListener("click", () => {
    if (state.busy) { toast('当前任务进行中，请等待完成后再新建'); return; }
    state.job = null;
    state.activeId = null;
    els.articlePanel.hidden = true;
    els.empty.hidden = false;
    els.plan.hidden = true;
    els.url.value = ""; els.sourceText.value = ""; els.sourceTitle.value = "";
    history.replaceState(null, "", "/article-visual");
    els.hint.textContent = "支持公开公众号文章 · 拆解包含策划与原文核对";
    els.hint.classList.remove("is-error");
    els.stickerLink.hidden = true;
    setTab("plan");
    els.url.focus();
  });
  els.stickerLink.addEventListener('click', () => {
    const value = els.url.value;
    window.AppNav?.setActiveView('sticker-extract', true);
    const input = $('sticker-url');
    if (input) { input.value = value; input.focus({preventScroll:true}); }
  });
  els.url.addEventListener('input', () => { els.stickerLink.hidden = true; });
  $('av-new').addEventListener('click', () => els.reset.click());
  window.CreationHistory?.register('article-visual', async item => {
    if (state.busy) { toast('当前任务进行中，请等待完成后再切换'); return false; }
    await loadJob(item.id); history.replaceState(null, '', `/article-visual?job=${encodeURIComponent(item.id)}`); return true;
  });

  if (els.tabs) {
    els.tabs.querySelectorAll("[data-tab]").forEach((button) => {
      button.addEventListener("click", () => setTab(button.dataset.tab));
    });
  }

  els.analyze.addEventListener("click", analyze);
  els.url.addEventListener("keydown", (event) => {
    if (event.key === "Enter") analyze();
  });

  // SPA 内嵌视图：切到这个 tab 时才初始化一次（保留 URL 里的 job 续接）。
  let booted = false;
  let inputOwner = null;
  window.ArticleVisual = {
    ensureLoaded() {
      if (booted) return;
      booted = true;
      const jobId = new URLSearchParams(window.location.search).get("job");
      (async () => {
        await initialAccountReady;
        const owner = currentAccount?.id;
        inputOwner = owner || null;
        let pending = false; try { pending = !!(owner && JSON.parse(localStorage.getItem(`article-visual-pending:${owner}`) || 'null')); } catch {}
        if (pending) await resumePending();
        else { if (jobId) await loadJob(jobId); await resumePending(); }
      })().catch(error => { els.hint.textContent = error.message; });
      els.url.focus();
    },
  };
  window.addEventListener('account-changed', () => {
    const owner = currentAccount?.id || null;
    if (inputOwner && inputOwner !== owner) {
      els.sourceText.value = ''; els.sourceTitle.value = ''; els.url.value = '';
      state.job = null; state.activeId = null;
      els.articlePanel.hidden = true; els.plan.hidden = true; els.empty.hidden = false;
    }
    inputOwner = owner;
    if (booted) resumePending();
  });

  // 直接打开 /article-visual 时 app.js 可能早于本脚本初始化，补一次首屏初始化。
  if (location.pathname.replace(/\/+$/, "") === "/article-visual") {
    window.ArticleVisual.ensureLoaded();
  }
})();
