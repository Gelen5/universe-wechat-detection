const form = document.querySelector('#diagnose-form');
const input = document.querySelector('#account-name');
const button = document.querySelector('#submit-button');
const reportRoot = document.querySelector('#report');
const downloadButton = document.querySelector('#download-report');
const appShell = document.querySelector('.app-shell');
const morningGenerator = document.querySelector('#morning-generator');
const apiSettingsButton = document.querySelector('#api-settings-button');
const apiSettingsModal = document.querySelector('#api-settings-modal');
const sharedTextKeyInput = document.querySelector('#shared-text-api-key');
const sharedImageKeyInput = document.querySelector('#shared-image-api-key');
const morningFrame = document.querySelector('.generator-frame');
const sharedKeys = { text: 'shared_text_api_key_v1', image: 'shared_image_api_key_v1' };

const esc = (value) => String(value ?? '无').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
const number = (value) => new Intl.NumberFormat('zh-CN').format(Number(value || 0));
const one = (value) => Number(value || 0).toFixed(1);
const safeUrl = (value) => {
  const raw = String(value || '').trim();
  if (/^https?:\/\//i.test(raw)) return raw;
  if (/^\/\//.test(raw)) return `https:${raw}`;
  return '';
};
const cleanApiKey = (value) => String(value || '').replace(/[\s\u00a0\u200b-\u200d\ufeff]/g, '');
const getSharedTextKey = () => cleanApiKey(localStorage.getItem(sharedKeys.text) || '');
const getSharedImageKey = () => cleanApiKey(localStorage.getItem(sharedKeys.image) || '');
const sharedApiPayload = () => ({
  textApiKey: getSharedTextKey(),
  imageApiKey: getSharedImageKey(),
});

function syncMorningApiKey() {
  morningFrame?.contentWindow?.postMessage({ type: 'shared-api-keys', imageApiKey: getSharedImageKey() }, window.location.origin);
}

function openApiSettings() {
  sharedTextKeyInput.value = getSharedTextKey();
  sharedImageKeyInput.value = getSharedImageKey();
  apiSettingsModal.hidden = false;
  sharedTextKeyInput.focus();
}

function closeApiSettings() {
  apiSettingsModal.hidden = true;
}

function saveApiSettings() {
  const textKey = cleanApiKey(sharedTextKeyInput.value);
  const imageKey = cleanApiKey(sharedImageKeyInput.value);
  if (textKey) localStorage.setItem(sharedKeys.text, textKey); else localStorage.removeItem(sharedKeys.text);
  if (imageKey) localStorage.setItem(sharedKeys.image, imageKey); else localStorage.removeItem(sharedKeys.image);
  sharedTextKeyInput.value = textKey;
  sharedImageKeyInput.value = imageKey;
  syncMorningApiKey();
  closeApiSettings();
}

apiSettingsButton?.addEventListener('click', openApiSettings);
document.querySelector('#api-settings-close')?.addEventListener('click', closeApiSettings);
document.querySelector('#api-settings-save')?.addEventListener('click', saveApiSettings);
document.querySelector('#api-settings-clear')?.addEventListener('click', () => {
  localStorage.removeItem(sharedKeys.text);
  localStorage.removeItem(sharedKeys.image);
  sharedTextKeyInput.value = '';
  sharedImageKeyInput.value = '';
  syncMorningApiKey();
});
apiSettingsModal?.addEventListener('click', (event) => {
  if (event.target === apiSettingsModal) closeApiSettings();
});
morningFrame?.addEventListener('load', syncMorningApiKey);

function scoreState(score) { return Number(score) < 45 ? ['偏低', 'low'] : Number(score) < 70 ? ['中等', 'mid'] : ['较好', 'good']; }

function renderWorks(works) {
  if (!works?.length) return '<p class="evidence-footnote">近 7 天暂未获取到作品数据。</p>';
  const rows = works.slice(0, 5).map((work) => {
    const title = work['标题'] || work.title || '未命名作品';
    const url = safeUrl(work.workUrl || work.url || work.link);
    const titleHtml = url
      ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(title)}</a>`
      : `<span title="接口未返回文章链接">${esc(title)}</span>`;
    return `<tr><td>${titleHtml}</td><td>${esc(work['发布时间'] || work.publishTime || '暂无')}</td><td>${number(work['阅读数'])}</td><td>${number(work['在看数'])}</td><td>${number(work['评论数'])}</td><td>${number(work['点赞数'])}</td></tr>`;
  }).join('');
  return `<table><thead><tr><th>标题</th><th>发布时间</th><th>阅读数</th><th>在看数</th><th>评论数</th><th>点赞数</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function renderLenses(dimensions) {
  const classes = ['', 'sage', 'orange', 'red'];
  return (dimensions || []).map((item, index) => {
    const [label, state] = scoreState(item.score);
    return `<article class="lens ${classes[index] || ''}"><span class="lens-index">0${index + 1}</span><h3>${esc(item.name)}</h3><span class="lens-score">${one(item.score)}<small> / 100</small></span><span class="lens-status ${state}">${label}</span><p>${esc(item.description)}</p></article>`;
  }).join('');
}

function renderRoute(recommendations) {
  const items = (recommendations || []).slice(0, 5);
  const periods = ['第 1 周 · 建立基线', '第 1–2 周 · 提升互动', '第 2 周 · 收窄定位', '第 2–3 周 · 优化标题', '第 4 周 · 复盘迭代'];
  return items.map((item, index) => `<article class="route-item"><span class="route-number">${String(index + 1).padStart(2, '0')}</span><div class="route-copy"><div class="route-kicker">${esc(periods[index] || '持续执行')} · ${esc(item.priority || '重点')}</div><h3>${esc(item.title)}</h3><p class="route-evidence"><b>当前问题：</b>${esc(item.evidence || '根据当前账号数据制定执行动作。')}</p><p class="route-action"><b>执行动作：</b>${esc(item.action)}</p></div><div class="route-target"><strong>成功信号</strong>${esc(item.target)}</div></article>`).join('');
}

function renderTakeaways(items, emptyText) {
  const list = (items || []).map((item) => `<li>${esc(item)}</li>`).join('');
  return list || `<li>${esc(emptyText)}</li>`;
}

function renderBenchmarks(accounts) {
  return (accounts || []).map((account, index) => {
    const name = account['账号名称'] || account.name || '未命名账号';
    const id = account['账号ID'] || account.id || '';
    const url = account['账号链接'] || `https://open.weixin.qq.com/qr/code?username=${encodeURIComponent(id)}`;
    return `<a class="benchmark-item" href="${esc(safeUrl(url))}" target="_blank" rel="noreferrer"><span class="benchmark-index">0${index + 1}</span><span><strong>${esc(name)}</strong><small>${esc(id || '同赛道样本')}</small></span><span class="benchmark-arrow">↗</span></a>`;
  }).join('');
}

function renderReport(report) {
  const header = report.header || {};
  const scores = report.scores || {};
  const insight = report.web_insights || {};
  const diagnosis = insight.diagnosis || {};
  const dimensions = insight.dimensions || [];
  const weakest = [...dimensions].sort((a, b) => a.score - b.score)[0];
  const score = Number(scores['综合评分'] || 0);
  const subtitle = header['账号简介'] || '接口暂未返回账号简介';
  document.querySelector('#report-id').textContent = `${new Date().toISOString().slice(0, 10).replaceAll('-', '')}-${String(header['账号ID'] || '').slice(-4)}`;
  document.querySelector('#hero-score').textContent = one(score);
  document.querySelector('#hero-score-line').style.setProperty('--score', `${Math.max(0, Math.min(100, score))}%`);
  const industryOverall = scores['行业对标']?.['综合评分']?.['行业均值'] || '行业均值暂缺';
  document.querySelector('#hero-compare').textContent = `行业均值 ${industryOverall}`;
  document.querySelector('#quote-copy').textContent = diagnosis.headline || insight.verdict || '先把数据做成连续样本，再判断长期方向。';
  document.querySelector('#diagnosis-title').textContent = diagnosis.headline || insight.verdict || '暂未形成诊断结论。';
  document.querySelector('#diagnosis-copy').textContent = diagnosis.evidence || insight.summary || `${weakest ? `${weakest.name}是当前最低分维度。` : ''}以上判断来自近期作品和账号数据。`;
  document.querySelector('#positioning-title').textContent = '优先行动';
  document.querySelector('#positioning-copy').textContent = diagnosis.action || insight.overview_judgment || `${subtitle} 当前需要继续用作品数据验证定位。`;
  document.querySelector('#overview-judgment').textContent = insight.overview_judgment || insight.summary || '暂未形成足够数据结论。';
  document.querySelector('#sample-size').textContent = number(insight.sample_size);
  document.querySelector('#avg-read').textContent = number(insight.avg_read);
  document.querySelector('#interaction-rate').textContent = `${one(insight.interaction_rate)}%`;
  document.querySelector('#profile-description').textContent = subtitle;
  document.querySelector('#profile-type').textContent = header['账号类型'] || header['认证信息'] || '未知';
  document.querySelector('#profile-frequency').textContent = scores['行业对标']?.['更新频率']?.['本账号'] || `${number(insight.sample_size)}篇/近期`;
  document.querySelector('#profile-confidence').textContent = insight.confidence || '低';
  document.querySelector('#benchmark-intro').textContent = `${header['账号名'] || '当前账号'}的对标重点不是照搬内容，而是比较相似账号的选题结构、标题方式和更新机制。`;
  document.querySelector('#lens-grid').innerHTML = renderLenses(dimensions);
  document.querySelector('#works-table').innerHTML = renderWorks(report.works);
  document.querySelector('#route-list').innerHTML = renderRoute(insight.recommendations);
  document.querySelector('#benchmark-list').innerHTML = renderBenchmarks(report.similar_accounts);
  document.querySelector('#strength-list').innerHTML = renderTakeaways(insight.strengths, '当前样本不足，暂未提炼优势。');
  document.querySelector('#weakness-list').innerHTML = renderTakeaways(insight.weaknesses, '当前样本不足，暂未提炼短板。');
  document.querySelector('#entry').hidden = true;
  morningGenerator.hidden = true;
  reportRoot.hidden = false;
  appShell?.classList.remove('landing');
  appShell?.classList.add('has-report');
  document.title = `${header['账号名'] || '公众号'} · 诊断报告`;
}

form?.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  button.querySelector('span').textContent = '…';
  try {
    const response = await fetch('/api/diagnose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_name: input.value.trim(), textApiKey: getSharedTextKey() }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.message || '诊断失败，请稍后重试');
    renderReport(data.report);
    reportRoot.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    alert(error.message);
  } finally { button.disabled = false; button.querySelector('span').textContent = '↗'; }
});

downloadButton?.addEventListener('click', () => window.print());

// Content workbench: a thin, stateful UI over the installed Skill adapter.
const workbench = document.querySelector('#workbench');
const entry = document.querySelector('#entry');
const modeButtons = [...document.querySelectorAll('.mode-option')];
const workflowSteps = document.querySelector('#workflow-steps');
const topicInput = document.querySelector('#workbench-topic');
const startWorkbench = document.querySelector('#start-workbench');
const workbenchResult = document.querySelector('#workbench-result');
const topicList = document.querySelector('#topic-list');
const articleEditor = document.querySelector('#article-editor');
const generatedImages = document.querySelector('#generated-images');
let workbenchMode = 'interactive';
let workbenchSession = null;

function paintWorkflow(current = 1) {
  workflowSteps.innerHTML = ['选题', '框架', '写作', '反 AI', '配图', '排版', '预览', '发布'].map((name, index) => {
    const n = index + 1;
    const state = n < current ? 'done' : n === current ? 'active' : '';
    return `<div class="workflow-step ${state}"><span>${String(n).padStart(2, '0')}</span><div><strong>${name}</strong><small>${n === 1 ? '找到值得写的方向' : n === 2 ? '确定文章骨架' : n === 3 ? '形成完整初稿' : n === 4 ? '检查 AI 痕迹' : n === 5 ? '规划视觉表达' : n === 6 ? '生成公众号排版' : n === 7 ? '手机端预览效果' : '确认后进入草稿箱'}</small></div></div>`;
  }).join('');
}

function renderWorkbenchSession(session) {
  workbenchSession = session;
  workbenchResult.hidden = false;
  paintWorkflow(session.current_step || 1);
  const statusLabels = { calling_text_api: '文本 API 生成中', calling_image_api: '图片 API 生成中', rendering: '正在排版', awaiting_topic: '等待选择', ready_for_review: '等待确认', complete: '已完成', running: `第 ${session.current_step || 1} 步` };
  document.querySelector('#workbench-status').textContent = statusLabels[session.status] || `第 ${session.current_step || 1} 步`;
  document.querySelector('#result-title').textContent = session.topic || '未命名创作';
  articleEditor.value = session.article || '';
  const score = session.score?.score;
  document.querySelector('#score-label').textContent = score == null ? '反 AI 评分将在第 4 步生成' : `反 AI 综合评分 ${Number(score).toFixed(1)} · ${session.score.status === 'success' ? '统计层与模式层已完成' : '评分不可用'}`;
  const textModel = session.provider?.text?.model || '文本模型';
  const imageModel = session.provider?.image?.model || '图片模型';
  document.querySelector('#result-meta').textContent = session.framework ? `${session.framework.name} 框架 · ${session.persona || '默认人格'} · 文本 ${textModel} · 图片 ${imageModel}` : `选题由 ${textModel} 实时生成`;
  const suggestions = session.suggestions || [];
  topicList.innerHTML = session.current_step === 1 && suggestions.length ? `<div class="topic-head"><strong>先选一个方向</strong><span>也可以直接编辑下方文章</span></div>${suggestions.map(item => `<button class="topic-item" data-topic-id="${item.id}" type="button"><span class="topic-number">${String(item.id).padStart(2, '0')}</span><span><strong>${esc(item.title)}</strong><small>${esc(item.type)} · 热度 ${item.heat} · ${esc(item.reason)}</small></span><span>↗</span></button>`).join('')}` : session.framework ? `<div class="framework-summary"><span class="micro-label">当前框架</span><strong>${esc(session.framework.name)}</strong><p>${esc(session.framework.reason)}</p><div>${session.framework.outline.map((item, i) => `<span>${i + 1}. ${esc(item)}</span>`).join('')}</div></div>` : '';
  topicList.querySelectorAll('.topic-item').forEach(item => item.addEventListener('click', () => advance(Number(item.dataset.topicId), 2)));
  const images = session.images || [];
  generatedImages.hidden = !images.length;
  generatedImages.innerHTML = images.length ? `<div class="image-section-head"><div><span class="micro-label">API 生成配图</span><h3>封面与正文配图</h3></div><span>${images.length} 张 · 已自动压缩至微信限制内</span></div><div class="image-grid">${images.map(image => `<a href="${esc(image.url)}" target="_blank" rel="noopener"><img src="${esc(image.url)}" alt="${image.kind === 'cover' ? '文章封面' : '正文配图'}" /><span><strong>${image.kind === 'cover' ? '文章封面' : '正文配图'}</strong><small>${esc(image.model)} · ${Math.round(Number(image.bytes || 0) / 1024)} KB</small></span></a>`).join('')}</div>` : '';
}

async function callWorkbench(path, payload) {
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...sharedApiPayload(), ...payload }) });
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || data.message || '工作台执行失败');
  return data.session;
}

async function advance(selection = null, nextStep = null) {
  if (!workbenchSession) return;
  const target = nextStep || Math.min(8, (workbenchSession.current_step || 1) + 1);
  workbenchSession = await callWorkbench('/api/workbench/steps', { session_id: workbenchSession.id, step: target, selection, article: articleEditor.value });
  renderWorkbenchSession(workbenchSession);
}

modeButtons.forEach(button => button.addEventListener('click', () => { modeButtons.forEach(item => item.classList.remove('active')); button.classList.add('active'); workbenchMode = button.dataset.mode; }));
startWorkbench?.addEventListener('click', async () => {
  startWorkbench.disabled = true;
  const originalLabel = startWorkbench.innerHTML;
  startWorkbench.innerHTML = workbenchMode === 'auto' ? '正在完成全链路…' : '正在调用文本 API…';
  try {
    const session = await callWorkbench('/api/workbench/sessions', { topic: topicInput.value.trim(), mode: workbenchMode, persona: document.querySelector('#workbench-persona').value, theme: document.querySelector('#workbench-theme').value });
    renderWorkbenchSession(session);
    workbenchResult.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) { alert(error.message); } finally { startWorkbench.disabled = false; startWorkbench.innerHTML = originalLabel; }
});
document.querySelector('#run-next')?.addEventListener('click', async (event) => { const btn = event.currentTarget; const label = btn.textContent; btn.disabled = true; btn.textContent = 'API 执行中…'; try { await advance(); } catch (error) { alert(error.message); } finally { btn.disabled = false; btn.textContent = label; } });
document.querySelector('#open-preview')?.addEventListener('click', async () => {
  if (!workbenchSession) return;
  try { const session = await callWorkbench('/api/workbench/preview', { session_id: workbenchSession.id, article: articleEditor.value }); renderWorkbenchSession(session); window.open(session.preview_url, '_blank', 'noopener'); } catch (error) { alert(error.message); }
});
document.querySelector('#publish-draft')?.addEventListener('click', async () => {
  if (!workbenchSession) return;
  try { const session = await callWorkbench('/api/workbench/publish', { session_id: workbenchSession.id, draft: true }); renderWorkbenchSession(session); alert(session.publish?.message || '已完成'); } catch (error) { alert(error.message); }
});
articleEditor?.addEventListener('input', () => { if (workbenchSession) workbenchSession.article = articleEditor.value; });

document.querySelectorAll('.app-tabs [data-view]').forEach(tab => tab.addEventListener('click', event => {
  event.preventDefault();
  const view = tab.dataset.view;
  document.querySelectorAll('.app-tabs [data-view]').forEach(item => item.classList.toggle('active', item === tab));
  if (view === 'workbench') { workbench.hidden = false; morningGenerator.hidden = true; entry.hidden = true; reportRoot.hidden = true; appShell?.classList.add('workbench-active'); workbench.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  else if (view === 'morning') { workbench.hidden = true; morningGenerator.hidden = false; entry.hidden = true; reportRoot.hidden = true; appShell?.classList.add('workbench-active'); syncMorningApiKey(); morningGenerator.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
  else { workbench.hidden = true; morningGenerator.hidden = true; entry.hidden = false; reportRoot.hidden = true; appShell?.classList.remove('workbench-active'); window.scrollTo({ top: 0, behavior: 'smooth' }); }
}));
paintWorkflow();
