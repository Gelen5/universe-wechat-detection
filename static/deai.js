(() => {
  const $ = (id) => document.getElementById(id);
  const els = {
    form: $("deai-form"), content: $("deai-content"), count: $("deai-count"),
    mode: $("deai-mode"), depth: $("deai-depth"), depthValue: $("deai-depth-value"),
    cost: $("deai-cost"), submit: $("deai-submit"), error: $("deai-error"),
    progressTitle: $("deai-progress-title"), percent: $("deai-percent"), bar: $("deai-bar"),
    steps: $("deai-steps"), cancel: $("deai-cancel"), summary: $("deai-summary"),
    result: $("deai-result"), resultTitle: $("deai-result-title"),
    output: $("deai-output"), original: $("deai-original"),
    warnings: $("deai-warnings"), copy: $("deai-copy"), download: $("deai-download"),
  };
  if (!els.form) return;
  const ACTIVE = new Set(["queued", "running"]);
  const DEFAULT_STEPS = [
    { key: "scan", name: "检测 AI 痕迹" },
    { key: "rewrite", name: "定向改写" },
    { key: "audit", name: "保真与可读性复核" },
    { key: "output", name: "输出结果" },
  ];
  const state = { poller: null, job: null, requestKey: "" };

  const makeKey = () => window.crypto?.randomUUID?.() ||
    "deai-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);

  function points() {
    const size = (els.content.value || "").trim().length;
    return Math.max(3, Math.min(30, Math.ceil(size / 1000) * 3));
  }

  function refreshCost() {
    els.count.textContent = `${els.content.value.length} / 12000`;
    els.cost.textContent = String(points());
  }

  function version() {
    return document.querySelector('input[name="deai-version"]:checked')?.value || "V3.1";
  }

  function fillSteps(job) {
    const steps = Array.isArray(job?.steps) && job.steps.length ? job.steps : DEFAULT_STEPS.map((s) => ({ ...s, status: 0 }));
    els.steps.replaceChildren();
    steps.forEach((step, index) => {
      const li = document.createElement("li");
      const status = Number(step.status) || 0;
      li.className = "deai-step " + (status === 1 ? "is-running" : status === 2 ? "is-done" : "");
      const mark = document.createElement("i");
      mark.textContent = status === 2 ? "✓" : String(index + 1).padStart(2, "0");
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = step.name || step.key || "处理中";
      const detail = document.createElement("small");
      detail.textContent = step.detail || (status === 2 ? "完成" : status === 1 ? "进行中" : "等待");
      copy.append(title, detail);
      li.append(mark, copy);
      els.steps.append(li);
    });
  }

  function paint(job) {
    if (!job) return;
    state.job = job;
    const percent = Math.max(0, Math.min(100, Number(job.progress) || 0));
    els.percent.textContent = `${percent}%`;
    els.bar.style.width = `${percent}%`;
    const labels = { queued: "排队中", running: job.stage || "处理中", succeeded: "已完成", failed: "任务失败", canceled: "已取消" };
    els.progressTitle.textContent = labels[job.status] || job.stage || "处理中";
    els.cancel.hidden = !ACTIVE.has(job.status);
    fillSteps(job);
    els.summary.hidden = !job.summary;
    els.summary.textContent = job.summary || "";
    if (job.status === "succeeded" && job.content) {
      els.result.hidden = false;
      els.resultTitle.textContent = job.changed ? "已完成去 AI 味改写" : "复核完成，正文无需修改";
      els.output.textContent = job.content;
      els.original.textContent = job.original || "";
      const warnings = Array.isArray(job.warnings) ? job.warnings.filter(Boolean) : [];
      els.warnings.hidden = !warnings.length;
      els.warnings.textContent = warnings.join("\n");
    } else if (job.status !== "succeeded") {
      els.result.hidden = true;
    }
    if (job.error && job.status === "failed") showError(job.error);
  }

  function showError(message) {
    els.error.hidden = !message;
    els.error.textContent = message || "";
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    let payload = {};
    try { payload = await response.json(); } catch (_) { payload = {}; }
    if (!response.ok) {
      const detail = payload.detail;
      throw new Error(typeof detail === "string" ? detail : `请求失败（HTTP ${response.status}）`);
    }
    return payload;
  }

  function stopPolling() {
    if (state.poller) clearTimeout(state.poller);
    state.poller = null;
  }

  async function poll(id) {
    stopPolling();
    try {
      const payload = await request(`/api/deai/tasks/${encodeURIComponent(id)}`);
      paint(payload.job);
      if (ACTIVE.has(payload.job.status)) {
        state.poller = setTimeout(() => poll(id), 1800);
      } else {
        state.requestKey = makeKey();
        els.submit.disabled = false;
        els.submit.textContent = payload.job.status === "succeeded" ? "再处理一篇" : "重新提交";
      }
    } catch (error) {
      showError(error.message);
      state.poller = setTimeout(() => poll(id), 3200);
    }
  }

  async function submit(event) {
    event.preventDefault();
    showError("");
    const content = els.content.value.trim();
    if (content.length < 20) return showError("原文至少需要 20 个字符。");
    if (/^https?:\/\/mp\.weixin\.qq\.com\/\S+$/i.test(content)) {
      return showError("请先提取公众号正文，再提交去 AI 味；不要直接粘贴文章链接。");
    }
    els.submit.disabled = true;
    els.submit.textContent = "提交中…";
    els.result.hidden = true;
    try {
      const payload = await request("/api/deai/tasks", {
        method: "POST",
        body: JSON.stringify({
          content,
          mode: els.mode.value,
          depth: Number(els.depth.value),
          version: version(),
          idempotency_key: state.requestKey || (state.requestKey = makeKey()),
        }),
      });
      paint(payload.job);
      els.submit.textContent = "处理中…";
      poll(payload.job.id);
    } catch (error) {
      showError(error.message);
      els.submit.disabled = false;
      els.submit.textContent = "开始去 AI 味";
    }
  }

  async function cancel() {
    if (!state.job?.id) return;
    els.cancel.disabled = true;
    try {
      const payload = await request(`/api/deai/tasks/${encodeURIComponent(state.job.id)}/cancel`, { method: "POST" });
      paint(payload.job);
      stopPolling();
      els.submit.disabled = false;
      els.submit.textContent = "重新提交";
    } catch (error) {
      showError(error.message);
    } finally {
      els.cancel.disabled = false;
    }
  }

  async function copy() {
    if (!state.job?.content) return;
    await navigator.clipboard.writeText(state.job.content);
    els.copy.textContent = "已复制";
    setTimeout(() => { els.copy.textContent = "复制"; }, 1400);
  }

  function download() {
    if (!state.job?.content) return;
    const blob = new Blob([state.job.content], { type: "text/markdown;charset=utf-8" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "去AI味成稿.md";
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  els.content.addEventListener("input", refreshCost);
  els.depth.addEventListener("input", () => { els.depthValue.textContent = els.depth.value; });
  els.form.addEventListener("submit", submit);
  els.cancel.addEventListener("click", cancel);
  els.copy.addEventListener("click", copy);
  els.download.addEventListener("click", download);
  state.requestKey = makeKey();
  refreshCost();
  fillSteps(null);
})();
