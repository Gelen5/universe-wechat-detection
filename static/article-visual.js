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

  const state = { job: null, activeId: null, busy: false, stamp: 0 };

  const $ = (id) => document.getElementById(id);
  const els = {
    url: $("av-url"),
    analyze: $("av-analyze"),
    hint: $("av-hint"),
    articlePanel: $("av-article-panel"),
    title: $("av-article-title"),
    meta: $("av-article-meta"),
    thesis: $("av-thesis"),
    reset: $("av-reset"),
    workspace: $("av-workspace"),
    list: $("av-slot-list"),
    count: $("av-count"),
    stageTitle: $("av-stage-title"),
    stageStatus: $("av-stage-status"),
    preview: $("av-preview"),
    previewImg: $("av-preview-img"),
    previewEmpty: $("av-preview-empty"),
    actions: $("av-actions"),
    note: $("av-note"),
    galleryPanel: $("av-gallery-panel"),
    gallery: $("av-gallery"),
    downloadAll: $("av-download-all"),
    toast: $("av-toast"),
  };

  function toast(message, ms = 2600) {
    els.toast.textContent = message;
    els.toast.hidden = false;
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => { els.toast.hidden = true; }, ms);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      headers: options.body ? { "Content-Type": "application/json" } : undefined,
      ...options,
    });
    let data = null;
    try { data = await response.json(); } catch (_) { /* ignore */ }
    if (!response.ok) {
      if (response.status === 401) {
        window.location.href = "/";
        throw new Error("请先登录");
      }
      const detail = (data && (data.detail || data.message)) || `请求失败（${response.status}）`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
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

  function render() {
    if (!state.job) return;
    const slots = state.job.slots;
    const done = slots.filter((s) => s.status === "done").length;

    els.title.textContent = state.job.article.title || "未命名文章";
    els.meta.textContent = [state.job.article.account, state.job.article.publish_time, `${state.job.article.chars} 字`]
      .filter(Boolean).join(" · ");
    els.thesis.textContent = state.job.plan.thesis ? `核心：${state.job.plan.thesis}` : "";
    els.count.textContent = `${done}/${slots.length} 张`;

    els.list.innerHTML = "";
    slots.forEach((slot, index) => {
      const li = document.createElement("li");
      li.className = "av-slot" + (slot.id === state.activeId ? " is-active" : "") + (slot.status === "done" ? " is-done" : "");
      li.dataset.id = slot.id;

      const badge = document.createElement("span");
      badge.className = "av-slot-index";
      badge.textContent = slot.status === "done" ? "✓" : String(index + 1);

      const body = document.createElement("div");
      body.className = "av-slot-body";
      const title = document.createElement("p");
      title.className = "av-slot-title";
      const tag = document.createElement("span");
      tag.className = "av-tag" + (slot.form === "cover" ? " av-tag-cover" : "");
      tag.textContent = FORM_LABEL[slot.form] || slot.form;
      title.appendChild(tag);
      title.appendChild(document.createTextNode(slot.headline || "未命名图位"));
      const sub = document.createElement("p");
      sub.className = "av-slot-sub";
      sub.textContent = slotSummary(slot) || slot.brief || "";
      body.appendChild(title);
      body.appendChild(sub);

      li.appendChild(badge);
      li.appendChild(body);
      li.addEventListener("click", () => {
        if (state.busy) return;
        state.activeId = slot.id;
        render();
      });
      els.list.appendChild(li);
    });

    const active = slots.find((s) => s.id === state.activeId) || slots[0];
    state.activeId = active.id;
    renderStage(active, slots);
  }

  function setStatus(text, kind) {
    els.stageStatus.textContent = text;
    els.stageStatus.className = "av-stage-status" + (kind ? ` is-${kind}` : "");
  }

  function renderStage(slot, slots) {
    els.stageTitle.textContent = `${FORM_LABEL[slot.form] || "图位"} · ${slot.headline || ""}`.trim();
    const url = imageUrl(slot.id);
    if (url) {
      els.previewImg.src = url;
      els.previewImg.hidden = false;
      els.previewEmpty.hidden = true;
      setStatus("已生成", "ok");
    } else {
      els.previewImg.hidden = true;
      els.previewImg.removeAttribute("src");
      els.previewEmpty.hidden = false;
      setStatus("等待生成");
    }

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
      go.addEventListener("click", () => generateRemaining());
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
    els.workspace.hidden = false;
    render();
    renderGallery();
  }

  async function analyze() {
    const url = els.url.value.trim();
    if (!url) { els.url.focus(); return; }
    state.busy = true;
    els.analyze.disabled = true;
    els.analyze.textContent = "拆解中…";
    els.hint.classList.remove("is-error");
    els.hint.textContent = "正在抓取正文并让模型拆解图位，约 10–20 秒。";
    try {
      const job = await api("/api/article-visual/plan", { method: "POST", body: JSON.stringify({ url }) });
      state.job = job;
      state.activeId = job.slots[0] ? job.slots[0].id : null;
      els.articlePanel.hidden = false;
      els.workspace.hidden = false;
      els.galleryPanel.hidden = true;
      history.replaceState(null, "", `/article-visual?job=${job.id}`);
      render();
      els.hint.textContent = "拆解完成。先点「生成封面」，满意后再继续。";
    } catch (error) {
      els.hint.classList.add("is-error");
      els.hint.textContent = error.message;
    } finally {
      state.busy = false;
      els.analyze.disabled = false;
      els.analyze.textContent = "拆解文章";
    }
  }

  async function generate(slotId, force) {
    if (state.busy || !state.job) return;
    state.busy = true;
    const slot = state.job.slots.find((s) => s.id === slotId);
    setStatus(force ? "重做中…" : "生成中…", "busy");
    els.actions.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      const result = await api(`/api/article-visual/${state.job.id}/generate`, {
        method: "POST",
        body: JSON.stringify({ slot_id: slotId }),
      });
      state.job.images[slotId] = { file: result.url.split("/").pop().split("?")[0] };
      const target = state.job.slots.find((s) => s.id === slotId);
      if (target) target.status = "done";
      state.stamp = Date.now();
      toast(force ? "这张已重做" : "生成完成");
      state.busy = false;
      render();
      renderGallery();
    } catch (error) {
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
    for (let index = 0; index < pending.length; index += 1) {
      const slot = pending[index];
      state.activeId = slot.id;
      render();
      setStatus(`正在生成 ${index + 1}/${pending.length}：${slot.headline}`, "busy");
      try {
        const result = await api(`/api/article-visual/${state.job.id}/generate`, {
          method: "POST",
          body: JSON.stringify({ slot_id: slot.id }),
        });
        state.job.images[slot.id] = { file: result.url.split("/").pop().split("?")[0] };
        slot.status = "done";
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
    setStatus("全部生成完成", "ok");
    render();
    renderGallery();
    toast("一套图出完了");
  }

  function renderGallery() {
    if (!state.job) return;
    const done = state.job.slots.filter((s) => state.job.images[s.id]);
    if (done.length < 2) { els.galleryPanel.hidden = true; return; }
    els.galleryPanel.hidden = false;
    els.gallery.innerHTML = "";
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
    state.job = null;
    state.activeId = null;
    els.articlePanel.hidden = true;
    els.workspace.hidden = true;
    els.galleryPanel.hidden = true;
    els.url.value = "";
    els.hint.textContent = "只支持 mp.weixin.qq.com 的公开文章；解析约 10–20 秒。";
    els.hint.classList.remove("is-error");
    els.url.focus();
  });

  els.analyze.addEventListener("click", analyze);
  els.url.addEventListener("keydown", (event) => {
    if (event.key === "Enter") analyze();
  });

  api("/api/auth/me")
    .then((data) => {
      const user = (data && (data.user || data)) || {};
      $("av-user").textContent = user.display_name || user.email || "已登录";
      const jobId = new URLSearchParams(window.location.search).get("job");
      if (jobId) loadJob(jobId).catch(() => {});
    })
    .catch(() => { /* api() 已处理 401 跳转 */ });
})();
