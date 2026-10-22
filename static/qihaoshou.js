import { readSSE } from "./qihaoshou-stream.js";
const $ = (id) => document.getElementById(id);
let current = null,
  capabilities = null,
  busy = false,
  dirty = false,
  controller = null,
  userId = "",
  range = null;
const frame = $("q-editor");
const fields = [
  "title",
  "topic",
  "audience",
  "style",
  "theme",
  "length",
  "reference",
  "instructions",
];
const body = () => frame.contentDocument?.body;
const op = () => ({
  session_id: current.id,
  revision: current.revision,
  request_id: crypto.randomUUID(),
});
function status(message, error = false) {
  $("q-status").textContent = message;
  $("q-status").classList.toggle("error", error);
}
async function api(path, options = {}) {
  const response = await fetch("/api/qihaoshou" + path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!response.ok) {
    const value = await response.json().catch(() => ({}));
    if (response.status === 401) showLogin();
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : response.status === 422
          ? "参数格式不正确，请检查输入"
          : "操作失败，请稍后重试",
    );
  }
  return response.json();
}
function showLogin() {
  $("q-login").hidden = false;
  $("q-studio").hidden = true;
}
function fill(data) {
  current = data;
  for (const key of fields) $("q-" + key).value = data[key] ?? "";
  $("q-source-url").value = data.reference_url || "";
  if (body()) body().innerHTML = data.html || "";
  $("q-save-state").textContent = "已保存 · 版本 " + data.revision;
  dirty = false;
}
function draft() {
  const data = {};
  for (const key of fields) data[key] = $("q-" + key).value;
  data.length = Number(data.length);
  data.reference_url = $("q-source-url").value.trim();
  data.html = body()?.innerHTML || "";
  data.revision = current?.revision || 0;
  return data;
}
function backup() {
  dirty = true;
  $("q-save-state").textContent = "有未保存修改";
  try {
    localStorage.setItem(
      "qhs-backup-" + userId,
      JSON.stringify({ session_id: current?.id, ...draft() }),
    );
  } catch {}
}
function controls() {
  document
    .querySelectorAll(
      "#q-studio button,#q-studio input,#q-studio select,#q-studio textarea,#q-new",
    )
    .forEach((el) => (el.disabled = busy));
  $("q-stop").hidden = !controller;
  $("q-stop").disabled = false;
  if (body()) body().contentEditable = String(!busy);
  if (!busy && capabilities) {
    $("q-generate").disabled = !capabilities.text;
    $("q-titles").disabled = !capabilities.text;
    $("q-deai").disabled = !capabilities.text;
    $("q-image").disabled = !capabilities.image;
    $("q-publish").disabled = !capabilities.wechat;
  }
}
async function task(fn) {
  if (busy) return;
  busy = true;
  controls();
  try {
    await fn();
  } catch (e) {
    status(e.message, true);
  } finally {
    busy = false;
    controller = null;
    controls();
    await wallet();
  }
}
async function wallet() {
  try {
    const r = await fetch("/api/auth/me");
    if (r.ok) {
      const d = await r.json();
      $("q-wallet").textContent = d.wallet.balance + " 积分";
    }
  } catch {}
}
async function history() {
  const result = await api("/sessions");
  const select = $("q-history");
  select.replaceChildren(new Option("选择历史文章", ""));
  for (const s of result.sessions)
    select.add(new Option(s.title.slice(0, 30), s.id));
  if (current) select.value = current.id;
}
async function save() {
  const value = draft();
  const saved = await api(current ? "/sessions/" + current.id : "/sessions", {
    method: current ? "PUT" : "POST",
    body: JSON.stringify(value),
  });
  current = saved;
  dirty = false;
  $("q-save-state").textContent = "已保存 · 版本 " + saved.revision;
  // Apply the server's sanitized version before copy/export or extensions.
  if (body()) body().innerHTML = saved.html;
  try {
    localStorage.removeItem("qhs-backup-" + userId);
  } catch {}
  await history();
  return saved;
}
async function extension(path, extra = {}) {
  await save();
  const result = await api(path, {
    method: "POST",
    body: JSON.stringify({ ...op(), ...extra }),
  });
  if (result.kind === "qihaoshou") fill(result);
  return result;
}
function setupEditor() {
  const doc = frame.contentDocument;
  if (!doc || doc.body.dataset.ready) return;
  doc.body.dataset.ready = "yes";
  if (current) doc.body.innerHTML = current.html || "";
  doc.addEventListener("selectionchange", () => {
    const selection = doc.getSelection();
    if (selection?.rangeCount) range = selection.getRangeAt(0).cloneRange();
  });
  doc.body.addEventListener("input", backup);
  // Pasting plain text avoids importing active markup or remote image trackers.
  doc.body.addEventListener("paste", (e) => {
    if (busy) return;
    e.preventDefault();
    const div = doc.createElement("div");
    div.textContent = e.clipboardData.getData("text/plain");
    doc.execCommand("insertHTML", false, div.innerHTML.replace(/\n/g, "<br>"));
    backup();
  });
}
frame.addEventListener("load", setupEditor);
setupEditor();
function command(name, value) {
  if (busy || !body()) return;
  const doc = frame.contentDocument;
  frame.contentWindow.focus();
  if (range) {
    const selection = doc.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  }
  doc.execCommand(name, false, value || null);
  backup();
}
$("q-toolbar").addEventListener("mousedown", (e) => {
  if (e.target.closest("button")) e.preventDefault();
});
$("q-toolbar").addEventListener("click", (e) => {
  const button = e.target.closest("[data-command]");
  if (button) command(button.dataset.command, button.dataset.value);
});
$("q-color").addEventListener("input", () =>
  command("foreColor", $("q-color").value),
);
$("q-font").addEventListener("change", () => {
  command("fontSize", "7");
  const doc = frame.contentDocument;
  doc.querySelectorAll('font[size="7"]').forEach((font) => {
    const span = doc.createElement("span");
    span.style.fontSize = $("q-font").value;
    while (font.firstChild) span.append(font.firstChild);
    font.replaceWith(span);
  });
  backup();
});
for (const key of [...fields, "source-url"])
  $("q-" + key).addEventListener("input", backup);
$("q-save").onclick = () =>
  task(async () => {
    await save();
    status("草稿已保存");
  });
$("q-new").onclick = () =>
  task(async () => {
    if (dirty && !confirm("当前有未保存修改，确定新建文章？")) return;
    current = null;
    fill({
      id: null,
      title: "",
      topic: "",
      audience: "公众号读者",
      style: "casual",
      theme: "green",
      length: 1200,
      reference: "",
      reference_url: "",
      instructions: "",
      html: "",
      revision: 0,
    });
    current = null;
    $("q-stream").textContent = "写下主题，开始新文章。";
    $("q-save-state").textContent = "尚未保存";
    $("q-title-list").replaceChildren();
    $("q-history").value = "";
    status("准备就绪");
  });
$("q-history").onchange = () =>
  task(async () => {
    const id = $("q-history").value;
    if (!id) return;
    if (dirty && !confirm("当前有未保存修改，确定切换草稿？")) return;
    fill(await api("/sessions/" + id));
    $("q-stream").textContent = "已恢复历史草稿，可以继续编辑或重新生成。";
    status("历史草稿已恢复");
  });
$("q-generate").onclick = () =>
  task(async () => {
    if (!$("q-topic").value.trim()) throw new Error("请先输入文章主题");
    if (
      body()?.textContent.trim() &&
      !confirm("生成成功后将替换当前正文，失败时保留原稿。继续？")
    )
      return;
    await save();
    controller = new AbortController();
    controls();
    $("q-stream").textContent = "";
    status("正在连接模型…");
    let completed = false;
    try {
      const response = await fetch("/api/qihaoshou/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(op()),
        signal: controller.signal,
      });
      if (!response.ok) {
        const value = await response.json();
        throw new Error(
          typeof value.detail === "string" ? value.detail : "生成请求失败",
        );
      }
      for await (const event of readSSE(response.body)) {
        if (event.error) throw new Error(event.error);
        if (event.progress) status(event.progress);
        if (event.token) {
          $("q-stream").textContent += event.token;
          $("q-stream").scrollTop = $("q-stream").scrollHeight;
        }
        if (event.article) {
          fill(event.article);
          completed = Boolean(event.done);
        }
      }
      if (!completed)
        throw new Error("连接中断，原稿仍保留。请重新加载草稿查看任务结果。");
      status("文章已生成并保存，可以编辑和排版");
      await history();
    } catch (e) {
      if (e.name === "AbortError")
        status("停止请求已发送，请重新加载草稿核对最终状态");
      else throw e;
    }
  });
$("q-stop").onclick = () => controller?.abort();
$("q-layout").onclick = () =>
  task(async () => {
    await extension("/render");
    status("主题已应用，正文内容未重新生成");
  });
$("q-titles").onclick = () =>
  task(async () => {
    status("正在生成候选标题…");
    const result = await extension("/titles");
    $("q-title-list").replaceChildren();
    for (const title of result.titles) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = title;
      button.onclick = () => {
        $("q-title").value = title;
        const heading = body()?.querySelector("h1");
        if (heading) heading.textContent = title;
        backup();
      };
      $("q-title-list").append(button);
    }
    status("点击标题即可应用，记得保存");
  });
$("q-deai").onclick = () =>
  task(async () => {
    status("正在检查表达并优化，原稿将在检查通过后更新…");
    await extension("/deai");
    status("表达优化通过保意检查，已保存；不保证任何检测结果");
  });
$("q-image").onclick = () =>
  task(async () => {
    const prompt = $("q-image-prompt").value.trim();
    if (!prompt) throw new Error("请填写配图画面描述");
    status("正在生成配图，请稍候…");
    await extension("/image", { prompt });
    status("配图已插入正文并保存");
  });
$("q-copy").onclick = () =>
  task(async () => {
    await save();
    const html = current.html;
    if (!body()?.textContent.trim()) throw new Error("请先输入正文");
    if (body().querySelector("img")) {
      status("正文包含受登录保护的本地配图；完整图文请使用公众号草稿同步。");
    }
    if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined")
      throw new Error(
        "当前浏览器不支持带格式复制，请使用 HTTPS 浏览器或导出 HTML",
      );
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([body().innerText], { type: "text/plain" }),
      }),
    ]);
    status(
      body().querySelector("img")
        ? "文字格式已复制；配图请使用公众号草稿同步"
        : "带格式正文已复制",
    );
  });
$("q-export").onclick = () =>
  task(async () => {
    await save();
    const fragment = body().cloneNode(true);
    for (const img of fragment.querySelectorAll("img")) {
      const response = await fetch(img.getAttribute("src"));
      if (!response.ok) throw new Error("图片读取失败，未导出不完整文件");
      const blob = await response.blob();
      img.src = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(blob);
      });
    }
    const blob = new Blob(
      [
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>文章</title><body>' +
          fragment.innerHTML +
          "</body></html>",
      ],
      { type: "text/html;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download =
      (current.title || "文章").replace(/[\\/:*?"<>|]/g, "-") + ".html";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
    status("HTML 已导出，配图已内嵌");
  });
$("q-publish").onclick = () =>
  task(async () => {
    await save();
    if (
      !confirm(
        "确认将当前标题、正文和配图写入服务端配置的公众号草稿箱？不会群发。",
      )
    )
      return;
    status("正在上传素材并同步草稿…");
    const result = await api("/wechat-draft", {
      method: "POST",
      body: JSON.stringify({ ...op(), confirm: true }),
    });
    if (!result.media_id) throw new Error("微信未确认草稿创建");
    status("已写入公众号草稿箱（尚未发布），草稿 ID：" + result.media_id);
  });
window.addEventListener("beforeunload", (e) => {
  if (dirty || busy) {
    e.preventDefault();
    e.returnValue = "";
  }
});
$("q-login-form").onsubmit = async (e) => {
  e.preventDefault();
  $("q-login-error").textContent = "";
  const button = e.target.querySelector("button");
  button.disabled = true;
  try {
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: $("q-email").value,
        password: $("q-password").value,
      }),
    });
    const value = await r.json();
    if (!r.ok)
      throw new Error(
        typeof value.detail === "string" ? value.detail : "登录失败",
      );
    $("q-password").value = "";
    await initialize();
  } catch (error) {
    $("q-login-error").textContent = error.message;
  } finally {
    button.disabled = false;
  }
};
async function initialize() {
  const response = await fetch("/api/auth/me");
  if (!response.ok) {
    showLogin();
    return;
  }
  const me = await response.json();
  userId = me.user.id;
  capabilities = await api("/capabilities");
  $("q-style").replaceChildren(
    ...capabilities.styles.map((x) => new Option(x.name, x.id)),
  );
  $("q-theme").replaceChildren(
    ...capabilities.themes.map((x) => new Option(x.name, x.id)),
  );
  $("q-style").value = "casual";
  $("q-login").hidden = true;
  $("q-studio").hidden = false;
  $("q-provider").textContent =
    `文字模型：${capabilities.text ? "已配置" : "未配置"} · 图片模型：${capabilities.image ? "已配置" : "未配置"}`;
  $("q-cost").textContent = capabilities.pricing
    .map((p) => p.feature.replace("起号兽", "") + " " + p.points + "积分")
    .join(" / ");
  $("q-wechat-hint").textContent = capabilities.wechat
    ? "将写入管理员配置的公众号草稿箱，不会群发。"
    : "公众号同步需要管理员账号，并配置 AppID / AppSecret；当前可保存与导出。";
  controls();
  await history();
  await wallet();
  // Recover only through the backend sanitizer before displaying backup markup.
  try {
    const local = JSON.parse(
      localStorage.getItem("qhs-backup-" + userId) || "null",
    );
    if (local && confirm("发现本机未保存的写作内容，是否恢复为新草稿？")) {
      const { session_id, ...value } = local;
      value.revision = 0;
      fill(
        await api("/sessions", { method: "POST", body: JSON.stringify(value) }),
      );
      localStorage.removeItem("qhs-backup-" + userId);
      status("本机未保存稿已恢复为新草稿");
      await history();
    }
  } catch {
    status("本机草稿无法自动恢复，请检查浏览器存储", true);
  }
}
initialize().catch((e) => {
  showLogin();
  $("q-login-error").textContent = "初始化失败：" + e.message;
});
