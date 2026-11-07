(() => {
  const $ = (id) => document.getElementById(id);
  const els = {
    search: $("skills-search"), groups: $("skills-groups"), grid: $("skills-grid"),
    empty: $("skills-empty"), dialog: $("skill-dialog"),
    group: $("skill-dialog-group"), name: $("skill-dialog-name"), desc: $("skill-dialog-desc"),
    version: $("skill-dialog-version"), directory: $("skill-dialog-directory"),
    prompt: $("skill-dialog-prompt"), input: $("skill-input"), run: $("skill-run-button"),
    error: $("skill-run-error"), result: $("skill-run-result"), output: $("skill-output"),
    copy: $("skill-copy"),
  };
  if (!els.grid) return;
  const state = { groups: [], skills: [], filter: "全部", query: "", current: null, output: "" };

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

  function renderGroups() {
    const names = ["全部", ...state.groups.map((item) => item.name)];
    els.groups.replaceChildren();
    names.forEach((name) => {
      const button = document.createElement("button");
      button.type = "button";
      button.role = "tab";
      button.textContent = name;
      button.setAttribute("aria-selected", String(state.filter === name));
      button.addEventListener("click", () => {
        state.filter = name;
        renderGroups();
        renderGrid();
      });
      els.groups.append(button);
    });
  }

  function iconNode(skill) {
    if (skill.icon) {
      const image = document.createElement("img");
      image.className = "skill-card-icon";
      image.src = skill.icon;
      image.alt = "";
      image.loading = "lazy";
      image.addEventListener("error", () => {
        image.replaceWith(fallbackIcon(skill));
      });
      return image;
    }
    return fallbackIcon(skill);
  }

  function fallbackIcon(skill) {
    const span = document.createElement("span");
    span.className = "skill-card-icon";
    span.textContent = (skill.name || "技").slice(0, 1);
    return span;
  }

  function visibleSkills() {
    const query = state.query.trim().toLowerCase();
    return state.skills.filter((skill) => {
      if (state.filter !== "全部" && skill.groupName !== state.filter) return false;
      if (!query) return true;
      return [skill.name, skill.description, skill.coreValue, skill.category]
        .some((value) => String(value || "").toLowerCase().includes(query));
    });
  }

  function renderGrid() {
    const skills = visibleSkills();
    els.grid.replaceChildren();
    els.empty.hidden = skills.length > 0;
    skills.forEach((skill) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "skill-card";
      const top = document.createElement("div");
      top.className = "skill-card-top";
      top.append(iconNode(skill));
      const names = document.createElement("div");
      const title = document.createElement("h3");
      title.textContent = skill.name;
      const group = document.createElement("small");
      group.textContent = skill.groupName;
      names.append(title, group);
      top.append(names);
      const desc = document.createElement("p");
      desc.textContent = skill.description || skill.coreValue || "暂无描述";
      const foot = document.createElement("div");
      foot.className = "skill-card-foot";
      const version = document.createElement("span");
      version.textContent = `v${skill.version}`;
      const action = document.createElement("span");
      action.textContent = "打开技能 →";
      foot.append(version, action);
      card.append(top, desc, foot);
      card.addEventListener("click", () => openSkill(skill));
      els.grid.append(card);
    });
  }

  async function openSkill(skill) {
    state.current = skill;
    state.output = "";
    els.error.hidden = true;
    els.result.hidden = true;
    els.input.value = "";
    els.group.textContent = skill.groupName;
    els.name.textContent = skill.name;
    els.desc.textContent = skill.description || skill.coreValue || "";
    els.version.textContent = `v${skill.version}`;
    els.directory.textContent = skill.directoryPath || "内置技能";
    els.prompt.textContent = "加载中…";
    if (typeof els.dialog.showModal === "function") els.dialog.showModal();
    else els.dialog.setAttribute("open", "");
    try {
      const payload = await request(`/api/skill-library/${encodeURIComponent(skill.id)}`);
      els.prompt.textContent = payload.skill.promptPreview || "该技能没有公开提示词预览。";
    } catch (error) {
      els.prompt.textContent = error.message;
    }
  }

  async function runSkill() {
    if (!state.current) return;
    const input = els.input.value.trim();
    els.error.hidden = true;
    if (input.length < 2) {
      els.error.hidden = false;
      els.error.textContent = "请输入主题或原文。";
      return;
    }
    els.run.disabled = true;
    els.run.textContent = "运行中…";
    try {
      const payload = await request(`/api/skill-library/${encodeURIComponent(state.current.id)}/run`, {
        method: "POST",
        body: JSON.stringify({ input }),
      });
      state.output = payload.content || "";
      els.output.textContent = state.output;
      els.result.hidden = false;
    } catch (error) {
      els.error.hidden = false;
      els.error.textContent = error.message;
    } finally {
      els.run.disabled = false;
      els.run.textContent = "运行这个技能";
    }
  }

  async function copy() {
    if (!state.output) return;
    await navigator.clipboard.writeText(state.output);
    els.copy.textContent = "已复制";
    setTimeout(() => { els.copy.textContent = "复制"; }, 1400);
  }

  async function load() {
    try {
      const payload = await request("/api/skill-library");
      state.groups = payload.groups || [];
      state.skills = payload.skills || [];
      renderGroups();
      renderGrid();
    } catch (error) {
      els.empty.hidden = false;
      els.empty.textContent = error.message;
    }
  }

  els.search.addEventListener("input", () => {
    state.query = els.search.value;
    renderGrid();
  });
  els.run.addEventListener("click", runSkill);
  els.copy.addEventListener("click", copy);
  load();
})();
