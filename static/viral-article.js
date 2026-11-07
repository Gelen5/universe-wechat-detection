/* 爆文复刻：多链接提交、轮询进度与安全渲染成稿 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const els = {
    urls: $("va-urls"),
    count: $("va-url-count"),
    angle: $("va-angle"),
    deai: $("va-deai"),
    chars: $("va-chars"),
    form: $("va-form"),
    submit: $("va-submit"),
    error: $("va-error"),
    cost: $("va-cost"),
    status: $("va-progress-title"),
    percent: $("va-percent"),
    bar: $("va-progress-bar"),
    steps: $("va-steps"),
    warnings: $("va-warnings"),
    warningList: $("va-warning-list"),
    cancel: $("va-cancel"),
    result: $("va-result"),
    resultTitle: $("va-result-title"),
    resultContent: $("va-result-content"),
    evidence: $("va-evidence"),
    evidenceBody: $("va-evidence-body"),
    copyTitle: $("va-copy-title"),
    copyContent: $("va-copy-content"),
    download: $("va-download"),
  };
  if (!els.form || !els.urls) return;

  const ACTIVE = new Set(["queued", "running"]);
  const BASE_POINTS = 10;
  const DEAI_POINTS = 13;
  const DEFAULT_STEPS = [
    { key: "fetch", name: "分析内容" },
    { key: "images", name: "解析配图" },
    { key: "rewrite", name: "生成内容" },
    { key: "deai", name: "原创改写" },
    { key: "output", name: "输出成稿" },
  ];
  const state = {
    booted: false,
    busy: false,
    poller: null,
    job: null,
    requestKey: "",
    removeAi: true,
  };

  function makeKey() {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return "va-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
  }

  function parseUrls() {
    return els.urls.value
      .split(/[\s，,、；;]+/)
      .map((value) => value.trim())
      .filter(Boolean);
  }

  function refreshCount() {
    const count = parseUrls().length;
    els.count.textContent = `${count} / 10`;
    els.count.classList.toggle("is-over", count > 10);
  }

  function refreshCost() {
    els.cost.textContent = String(els.deai.checked ? DEAI_POINTS : BASE_POINTS);
  }

  function showError(message) {
    els.error.textContent = message || "";
    els.error.hidden = !message;
  }

  function detailMessage(payload, status) {
    let detail = payload?.detail;
    if (detail && typeof detail === "object") {
      detail = detail.reason || detail.message || JSON.stringify(detail);
    }
    if (status === 401) return "请先登录后再提交。";
    if (status === 402) return detail || "积分不足，请先充值。";
    return detail || `请求失败（HTTP ${status}）`;
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }
    if (!response.ok) throw new Error(detailMessage(payload, response.status));
    return payload;
  }

  function stepList(job) {
    const shown = Array.isArray(job?.steps) ? job.steps : [];
    if (shown.length) return shown;
    return DEFAULT_STEPS.filter((step) => state.removeAi || step.key !== "deai")
      .map((step) => ({ ...step, status: 0, detail: "" }));
  }

  function paintSteps(job) {
    const statusText = { 0: "等待", 1: "进行中", 2: "完成", 3: "失败" };
    const statusClass = { 0: "", 1: "is-running", 2: "is-done", 3: "is-failed" };
    els.steps.replaceChildren();
    stepList(job).forEach((step, index) => {
      const item = document.createElement("li");
      item.className = "va-step " + (statusClass[step.status] || "");
      const mark = document.createElement("i");
      mark.textContent = step.status === 2 ? "✓" : String(index + 1).padStart(2, "0");
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = step.name || step.key || "处理中";
      const detail = document.createElement("small");
      detail.textContent = step.detail || "";
      copy.append(title, detail);
      const badge = document.createElement("span");
      badge.className = "va-step-status";
      badge.textContent = statusText[step.status] || "等待";
      item.append(mark, copy, badge);
      els.steps.append(item);
    });
  }

  function safeUrl(value) {
    try {
      const url = new URL(value, window.location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_) {
      return "";
    }
  }

  function paintEvidence(job) {
    els.evidenceBody.replaceChildren();
    const sources = Array.isArray(job.sources) ? job.sources : [];
    const facts = Array.isArray(job.facts) ? job.facts : [];
    if (!sources.length && !facts.length) {
      const empty = document.createElement("p");
      empty.textContent = "本次未返回结构化来源或事实账本，请人工复核。";
      els.evidenceBody.append(empty);
      return;
    }
    if (sources.length) {
      const heading = document.createElement("h3");
      heading.textContent = "来源";
      const list = document.createElement("ul");
      sources.forEach((source) => {
        const item = document.createElement("li");
        const href = safeUrl(source.url);
        if (href) {
          const link = document.createElement("a");
          link.href = href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          link.textContent = source.title || href;
          item.append(link);
        } else {
          item.textContent = source.title || "来源地址无效";
        }
        if (source.platform) item.append(` · ${source.platform}`);
        list.append(item);
      });
      els.evidenceBody.append(heading, list);
    }
    if (facts.length) {
      const heading = document.createElement("h3");
      heading.textContent = "事实账本";
      const list = document.createElement("ul");
      facts.slice(0, 80).forEach((fact) => {
        const item = document.createElement("li");
        item.textContent = fact.claim || "";
        if (fact.quote) item.append(`（原文：${fact.quote}）`);
        list.append(item);
      });
      els.evidenceBody.append(heading, list);
    }
  }

  function paintWarnings(job) {
    const warnings = Array.isArray(job?.warnings) ? job.warnings : [];
    els.warningList.replaceChildren();
    warnings.forEach((warning) => {
      const item = document.createElement("li");
      item.textContent = warning;
      els.warningList.append(item);
    });
    els.warnings.hidden = warnings.length === 0;
  }

  function paintJob(job) {
    if (!job) return;
    state.job = job;
    const active = ACTIVE.has(job.status);
    const percent = Math.max(0, Math.min(100, Number(job.progress) || 0));
    els.percent.textContent = `${percent}%`;
    els.bar.style.width = `${percent}%`;
    const labels = {
      queued: "排队中",
      running: job.stage || "处理中",
      succeeded: "已完成",
      failed: "任务失败",
      canceled: "已取消",
    };
    els.status.textContent = labels[job.status] || job.stage || "处理中";
    els.cancel.hidden = !active;
    els.cancel.disabled = Boolean(job.canceled_at);
    els.cancel.textContent = job.canceled_at ? "正在取消…" : "取消任务";
    paintSteps(job);
    paintWarnings(job);

    const content = job.results?.[0]?.content || "";
    if (job.status === "succeeded" && content) {
      els.result.hidden = false;
      els.resultTitle.textContent = job.title || "爆文复刻成稿";
      els.resultContent.textContent = content;
      paintEvidence(job);
    } else if (job.status !== "succeeded") {
      els.result.hidden = true;
    }
    if (job.error && job.status === "failed") showError(job.error);
  }

  function stopPolling() {
    if (state.poller) window.clearTimeout(state.poller);
    state.poller = null;
  }

  async function poll(jobId) {
    stopPolling();
    try {
      const payload = await request(`/api/viral-article/tasks/${encodeURIComponent(jobId)}`);
      paintJob(payload.job);
      if (ACTIVE.has(payload.job.status)) {
        state.poller = window.setTimeout(() => poll(jobId), 1800);
      } else {
        state.requestKey = makeKey();
        state.busy = false;
        els.submit.disabled = false;
        els.submit.textContent = payload.job.status === "succeeded" ? "再复刻一篇" : "重新提交";
      }
    } catch (error) {
      state.poller = window.setTimeout(() => poll(jobId), 3000);
      if (!els.error.hidden) return;
      showError("进度刷新失败，正在重试：" + error.message);
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (state.busy) return;
    const urls = parseUrls();
    if (!urls.length) return showError("请至少输入一条公开文章链接。");
    if (urls.length > 10) return showError("最多输入 10 条文章链接。");
    const chars = els.chars.value.trim() ? Number(els.chars.value) : null;
    if (chars !== null && (!Number.isInteger(chars) || chars < 200 || chars > 10000)) {
      return showError("目标字数需在 200 到 10000 之间。");
    }
    showError("");
    state.busy = true;
    state.removeAi = els.deai.checked;
    els.submit.disabled = true;
    els.submit.textContent = "正在提交…";
    try {
      const payload = await request("/api/viral-article/tasks", {
        method: "POST",
        body: JSON.stringify({
          urls,
          remove_ai_flavor: state.removeAi,
          new_angle: els.angle.value.trim(),
          target_characters: chars,
          idempotency_key: state.requestKey || makeKey(),
        }),
      });
      paintJob(payload.job);
      const jobUrl = `/viral-article?job=${encodeURIComponent(payload.job.id)}`;
      if (location.pathname + location.search !== jobUrl) history.replaceState(null, "", jobUrl);
      els.submit.textContent = ACTIVE.has(payload.job.status) ? "复刻进行中…" : "重新提交";
      if (ACTIVE.has(payload.job.status)) poll(payload.job.id);
      else {
        state.busy = false;
        els.submit.disabled = false;
        els.submit.textContent = payload.job.status === "succeeded" ? "再复刻一篇" : "重新提交";
      }
    } catch (error) {
      showError(error.message);
      els.submit.disabled = false;
      els.submit.textContent = "开始复刻";
      state.busy = false;
    }
  }

  async function cancel() {
    if (!state.job?.id) return;
    els.cancel.disabled = true;
    try {
      const payload = await request(`/api/viral-article/tasks/${encodeURIComponent(state.job.id)}/cancel`, {
        method: "POST",
        body: "{}",
      });
      paintJob(payload.job);
      if (ACTIVE.has(payload.job.status)) {
        els.submit.disabled = true;
        els.submit.textContent = "正在取消…";
        poll(payload.job.id);
      } else {
        stopPolling();
        state.busy = false;
        els.submit.disabled = false;
        els.submit.textContent = "重新提交";
      }
    } catch (error) {
      showError(error.message);
    } finally {
      els.cancel.disabled = false;
    }
  }

  async function copyText(value, button) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      const prior = button.textContent;
      button.textContent = "已复制";
      window.setTimeout(() => { button.textContent = prior; }, 1200);
    } catch (_) {
      showError("复制失败，请手动选择文本。");
    }
  }

  function download() {
    const title = els.resultTitle.textContent || "爆文复刻";
    const content = els.resultContent.textContent || "";
    if (!content) return;
    const blob = new Blob([`# ${title}\n\n${content}\n`], { type: "text/markdown;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = title.replace(/[\\/:*?"<>|]+/g, "-").slice(0, 80) + ".md";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  function boot() {
    if (state.booted) return;
    state.booted = true;
      // Keep the key fixed until a submission has a concrete result. Polling
      // refreshes live account state and can rerun app observers; replacing
      // the key on each keystroke caused accidental duplicate jobs.
      if (!state.requestKey) state.requestKey = makeKey();
    state.removeAi = els.deai.checked;
    els.urls.addEventListener("input", refreshCount);
    els.angle.addEventListener("input", refreshCount);
    els.chars.addEventListener("input", refreshCount);
    els.deai.addEventListener("change", refreshCost);
    els.form.addEventListener("submit", submit);
    els.cancel.addEventListener("click", cancel);
    els.copyTitle.addEventListener("click", () => copyText(els.resultTitle.textContent, els.copyTitle));
    els.copyContent.addEventListener("click", () => copyText(els.resultContent.textContent, els.copyContent));
    els.download.addEventListener("click", download);
    refreshCount();
    refreshCost();
    paintSteps({ steps: [] });
    const jobId = new URLSearchParams(location.search).get("job");
    if (jobId) {
      state.busy = true;
      els.submit.disabled = true;
      els.submit.textContent = "正在恢复任务…";
      request(`/api/viral-article/tasks/${encodeURIComponent(jobId)}`)
        .then((payload) => {
          paintJob(payload.job);
          if (ACTIVE.has(payload.job.status)) {
            els.submit.textContent = "复刻进行中…";
            poll(payload.job.id);
          } else {
            state.busy = false;
            els.submit.disabled = false;
            els.submit.textContent = payload.job.status === "succeeded" ? "再复刻一篇" : "重新提交";
          }
        })
        .catch(() => {
          history.replaceState(null, "", "/viral-article");
          state.busy = false;
          els.submit.disabled = false;
          els.submit.textContent = "开始复刻";
        });
    }
  }

  window.ViralArticle = { ensureLoaded: boot };
  if (location.pathname.replace(/\/+$/, "") === "/viral-article") boot();
})();
