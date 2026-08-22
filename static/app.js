const form = document.querySelector('#diagnose-form');
const input = document.querySelector('#account-name');
const button = document.querySelector('#submit-button');
const reportRoot = document.querySelector('#report');
const downloadButton = document.querySelector('#download-report');
const appShell = document.querySelector('.app-shell');

const esc = (value) => String(value ?? '无').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
const number = (value) => new Intl.NumberFormat('zh-CN').format(Number(value || 0));
const one = (value) => Number(value || 0).toFixed(1);
const safeUrl = (value) => {
  const raw = String(value || '').trim();
  if (/^https?:\/\//i.test(raw)) return raw;
  if (/^\/\//.test(raw)) return `https:${raw}`;
  return '';
};

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
