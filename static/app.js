const form = document.querySelector('#diagnose-form');
const input = document.querySelector('#account-name');
const button = document.querySelector('#submit-button');
const reportRoot = document.querySelector('#report');
const downloadButton = document.querySelector('#download-report');
const appShell = document.querySelector('.app-shell');

const esc = (value) => String(value ?? '无').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
const number = (value) => new Intl.NumberFormat('zh-CN').format(Number(value || 0));
const one = (value) => Number(value || 0).toFixed(1);
const safeUrl = (value) => /^https?:\/\//i.test(String(value || '')) ? String(value) : '#';

function scoreState(score) { return Number(score) < 45 ? ['偏低', 'low'] : Number(score) < 70 ? ['中等', 'mid'] : ['较好', 'good']; }

function renderWorks(works) {
  if (!works?.length) return '<p class="evidence-footnote">近 7 天暂未获取到作品数据。</p>';
  const rows = works.slice(0, 5).map((work) => `<tr><td><a href="${esc(safeUrl(work.workUrl || work.url))}" target="_blank" rel="noreferrer">${esc(work['标题'] || '未命名作品')}</a></td><td>${esc(work['发布时间'])}</td><td>${number(work['阅读数'])}</td><td>${number(work['在看数'])}</td><td>${number(work['评论数'])}</td><td>${number(work['点赞数'])}</td></tr>`).join('');
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
  const dimensions = insight.dimensions || [];
  const weakest = [...dimensions].sort((a, b) => a.score - b.score)[0];
  const score = Number(scores['综合评分'] || 0);
  const subtitle = header['账号简介'] || '情感陪伴 · 睡前文字';
  const direction = header['账号名'] === '滚去睡' ? '睡前情感陪伴' : '内容陪伴型账号';
  document.querySelector('#report-id').textContent = `${new Date().toISOString().slice(0, 10).replaceAll('-', '')}-${String(header['账号ID'] || '').slice(-4)}`;
  document.querySelector('#hero-score').textContent = one(score);
  document.querySelector('#hero-score-line').style.setProperty('--score', `${Math.max(0, Math.min(100, score))}%`);
  document.querySelector('#hero-compare').textContent = `低于同类账号 ${Math.max(0, 100 - score)}%`;
  document.querySelector('#quote-copy').textContent = insight.verdict || '先把数据做成连续样本，再判断长期方向。';
  document.querySelector('#diagnosis-title').textContent = insight.verdict?.split('，')[0] || '账号还在冷启动阶段。';
  document.querySelector('#diagnosis-copy').textContent = `内容调性清晰，但${weakest ? `${weakest.name}得分偏低，` : ''}互动与传播还没有形成可持续的反馈回路。建议先固定更新节奏，补齐内容证据，再考虑品牌化包装。`;
  document.querySelector('#positioning-title').textContent = direction;
  document.querySelector('#positioning-copy').textContent = `${subtitle} 当前最适合通过连续栏目建立识别度，让用户知道关注后下一次还会获得什么。`;
  document.querySelector('#lens-grid').innerHTML = renderLenses(dimensions);
  document.querySelector('#works-table').innerHTML = renderWorks(report.works);
  document.querySelector('#route-list').innerHTML = renderRoute(insight.recommendations);
  document.querySelector('#benchmark-list').innerHTML = renderBenchmarks(report.similar_accounts);
  document.querySelector('#entry').hidden = true;
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
    const response = await fetch('/api/diagnose', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ account_name: input.value.trim() }) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || data.message || '诊断失败，请稍后重试');
    renderReport(data.report);
    reportRoot.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    alert(error.message);
  } finally { button.disabled = false; button.querySelector('span').textContent = '↗'; }
});

downloadButton?.addEventListener('click', () => window.print());
