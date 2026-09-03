const form = document.querySelector('#diagnose-form');
const input = document.querySelector('#account-name');
const button = document.querySelector('#submit-button');
const reportRoot = document.querySelector('#report');
const downloadButton = document.querySelector('#download-report');
const appShell = document.querySelector('.app-shell');
const morningGenerator = document.querySelector('#morning-generator');
const settingsButton = document.querySelector('#settings-button');
const settingsMenu = document.querySelector('#settings-menu');
const apiSettingsButton = document.querySelector('#api-settings-button');
const apiSettingsModal = document.querySelector('#api-settings-modal');
const adminUsersButton = document.querySelector('#admin-users-button');
const adminUsersModal = document.querySelector('#admin-users-modal');
const sharedTextKeyInput = document.querySelector('#shared-text-api-key');
const sharedImageKeyInput = document.querySelector('#shared-image-api-key');
const sharedTextBaseUrlInput = document.querySelector('#shared-text-base-url');
const sharedImageBaseUrlInput = document.querySelector('#shared-image-base-url');
const sharedTextModelInput = document.querySelector('#shared-text-model');
const sharedImageModelInput = document.querySelector('#shared-image-model');
const morningFrame = document.querySelector('.generator-frame');
const textConfigStatus = document.querySelector('#text-config-status');
const imageConfigStatus = document.querySelector('#image-config-status');
const configDot = document.querySelector('#settings-config-dot');
const xiaohongshuPage = document.querySelector('#xiaohongshu');
const tieTuPage = document.querySelector('#tie-tu');
const hitDetectorPage = document.querySelector('#hit-detector');
const authModal = document.querySelector('#auth-modal');
const walletModal = document.querySelector('#wallet-modal');
const walletSettingsButton = document.querySelector('#wallet-settings-button');
const logoutButton = document.querySelector('#logout-button');
let currentAccount = null;
let currentWallet = { balance: 0, trial: 0, bonus: 0, paid: 0 };
const sharedKeys = {
  text: 'shared_text_api_key_v1',
  image: 'shared_image_api_key_v1',
  textBaseUrl: 'shared_text_base_url_v1',
  imageBaseUrl: 'shared_image_base_url_v1',
  textModel: 'shared_text_model_v1',
  imageModel: 'shared_image_model_v1',
};

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
const getStored = (key, fallback = '') => String(localStorage.getItem(key) ?? fallback);
const getTextBaseUrl = () => getStored(sharedKeys.textBaseUrl, 'https://huoxingapi.com/v1').trim();
const getImageBaseUrl = () => getStored(sharedKeys.imageBaseUrl, 'https://img.rjm.us.ci').trim();
const getTextModel = () => getStored(sharedKeys.textModel, 'deepseek-v4-flash').trim();
const getImageModel = () => getStored(sharedKeys.imageModel, 'gpt-image-2').trim();
const sharedApiPayload = () => ({});

function syncAdminVisibility() {
  const isAdmin = currentAccount?.role === 'admin' && currentAccount?.email?.toLowerCase() === 'gelen5@163.com';
  if (apiSettingsButton) apiSettingsButton.hidden = !isAdmin;
  if (adminUsersButton) adminUsersButton.hidden = !isAdmin;
  if (!isAdmin && apiSettingsModal) apiSettingsModal.hidden = true;
  if (!isAdmin && adminUsersModal) adminUsersModal.hidden = true;
  const impersonating = Boolean(currentAccount?.impersonation?.active);
  const banner = document.querySelector('#impersonation-banner');
  if (banner) banner.hidden = !impersonating;
  if (impersonating) document.querySelector('#impersonation-user-name').textContent = `${currentAccount.display_name}（${currentAccount.email}）`;
}

const formatDate = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '从未登录';

async function loadAdminUsers(query = '') {
  const [overviewData, usersData] = await Promise.all([
    readApiResponse(await fetch('/api/admin/overview')),
    readApiResponse(await fetch(`/api/admin/users?query=${encodeURIComponent(query)}`)),
  ]);
  const overview = overviewData.overview;
  const cards = [
    ['累计注册', overview.users], ['今日新增', overview.registered_today],
    ['近 7 天', overview.registered_7d], ['30 天活跃', overview.active_30d],
  ];
  document.querySelector('#admin-stats').innerHTML = cards.map(([label, value]) => `<article><span>${label}</span><strong>${number(value)}</strong></article>`).join('');
  const body = document.querySelector('#admin-users-list');
  body.innerHTML = usersData.users.map(user => `<tr data-user-row="${esc(user.id)}"><td><strong>${esc(user.display_name)}</strong><small>${esc(user.email)}</small></td><td>${esc(formatDate(user.created_at))}</td><td>${esc(formatDate(user.last_login_at))}</td><td><b>${number(user.balance)}</b></td><td>${number(user.completed_tasks)}</td><td><button type="button" data-view-user="${esc(user.id)}">详情</button></td></tr>`).join('') || '<tr><td colspan="6" class="admin-empty-row">没有找到用户</td></tr>';
  body.querySelectorAll('[data-view-user]').forEach(button => button.addEventListener('click', () => loadAdminUserDetail(button.dataset.viewUser)));
}

async function loadAdminTasks() {
  const data = await readApiResponse(await fetch('/api/admin/tasks?limit=100'));
  const body = document.querySelector('#admin-tasks-list');
  body.innerHTML = data.tasks.map(task => `<tr><td>${esc(task.type)}</td><td>${esc(task.lane)}</td><td><b>${esc(task.status)}</b></td><td>${esc(formatDate(task.created_at))}</td><td>${task.status === 'queued' || task.status === 'running' ? `<button type="button" data-refund-task="${esc(task.id)}">退款</button>` : '—'}</td></tr>`).join('') || '<tr><td colspan="5" class="admin-empty-row">暂无任务</td></tr>';
  body.querySelectorAll('[data-refund-task]').forEach(button => button.addEventListener('click', async () => {
    await readApiResponse(await fetch(`/api/admin/tasks/${encodeURIComponent(button.dataset.refundTask)}/refund`, { method: 'POST' }));
    await loadAdminTasks();
  }));
}

async function loadAdminUserDetail(userId) {
  const data = await readApiResponse(await fetch(`/api/admin/users/${encodeURIComponent(userId)}`));
  const user = data.user;
  document.querySelectorAll('[data-user-row]').forEach(row => row.classList.toggle('selected', row.dataset.userRow === userId));
  const transactions = user.transactions.map(item => `<li><span>${esc(formatDate(item.created_at))}</span><strong>${item.amount > 0 ? '+' : ''}${number(item.amount)} 分</strong><small>${esc(item.note || item.feature || item.kind)}</small></li>`).join('') || '<li class="empty">暂无积分记录</li>';
  document.querySelector('#admin-user-detail').innerHTML = `<div class="admin-detail-user"><span>${esc(user.display_name.slice(0, 1).toUpperCase())}</span><div><h3>${esc(user.display_name)}</h3><p>${esc(user.email)}</p></div></div><dl><div><dt>注册时间</dt><dd>${esc(formatDate(user.created_at))}</dd></div><div><dt>最后登录</dt><dd>${esc(formatDate(user.last_login_at))}</dd></div><div><dt>可用积分</dt><dd>${number(user.balance)}</dd></div><div><dt>完成任务</dt><dd>${number(user.usage.completed)}</dd></div></dl><div class="admin-balance-detail"><span>试用 ${number(user.trial_balance)}</span><span>赠送 ${number(user.bonus_balance)}</span><span>付费 ${number(user.paid_balance)}</span></div>${user.role === 'admin' ? '<p class="admin-owner-note">当前为管理员账号，不能切换。</p>' : `<button class="admin-switch-user" type="button" data-switch-user="${esc(user.id)}"><i data-lucide="arrow-right-left"></i>切换到该用户视角</button>`}<section class="admin-recent"><h4>最近积分记录</h4><ul>${transactions}</ul></section>`;
  document.querySelector('[data-switch-user]')?.addEventListener('click', event => switchToUser(event.currentTarget.dataset.switchUser));
  window.lucide?.createIcons();
}

async function openAdminUsers() {
  toggleSettingsMenu(false);
  adminUsersModal.hidden = false;
  try { await Promise.all([loadAdminUsers(), loadAdminTasks()]); } catch (error) { adminUsersModal.hidden = true; showToast(error.message, 'error'); }
}

async function switchToUser(userId) {
  if (!window.confirm('切换后将以该用户的积分和权限使用工作台。所有切换行为都会记录，是否继续？')) return;
  try {
    const data = await readApiResponse(await fetch('/api/admin/impersonate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId }) }));
    currentAccount = data.user;
    renderWallet(data.wallet);
    adminUsersModal.hidden = true;
    syncAdminVisibility();
    showToast(`已切换到 ${currentAccount.display_name} 的用户视角`);
  } catch (error) { showToast(error.message, 'error'); }
}

async function stopImpersonation() {
  try {
    const data = await readApiResponse(await fetch('/api/auth/stop-impersonation', { method: 'POST' }));
    currentAccount = data.user;
    renderWallet(data.wallet);
    syncAdminVisibility();
    showToast('已返回管理员账号');
  } catch (error) { showToast(error.message, 'error'); }
}

function syncMorningApiKey() {
  morningFrame?.contentWindow?.postMessage({
    type: 'shared-api-keys',
    serverManaged: true,
    useRealImage: true,
  }, window.location.origin);
}

function refreshConfigStatus() {
  const hasText = true;
  const hasImage = true;
  if (textConfigStatus) {
    textConfigStatus.textContent = '服务器托管';
    textConfigStatus.classList.toggle('ready', hasText);
  }
  if (imageConfigStatus) {
    imageConfigStatus.textContent = '服务器托管';
    imageConfigStatus.classList.toggle('ready', hasImage);
  }
  configDot?.classList.toggle('ready', hasText && hasImage);
  configDot?.classList.toggle('partial', hasText !== hasImage);
  document.querySelector('.api-live-dot')?.classList.toggle('offline', !currentAccount);
}

function showToast(message, type = 'success') {
  const toast = document.createElement('div');
  toast.className = `app-toast ${type}`;
  toast.innerHTML = `<i data-lucide="${type === 'success' ? 'check-circle-2' : 'circle-alert'}"></i><span>${esc(message)}</span>`;
  document.body.appendChild(toast);
  window.lucide?.createIcons();
  requestAnimationFrame(() => toast.classList.add('visible'));
  setTimeout(() => { toast.classList.remove('visible'); setTimeout(() => toast.remove(), 220); }, 2600);
}

async function readApiResponse(response) {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    if ([502, 503, 504].includes(response.status)) {
      throw new Error('AI 生成时间超过网关等待上限，任务可能仍在服务器继续执行。请先等待一分钟并刷新页面，避免重复提交。');
    }
    throw new Error(`服务器响应格式异常（HTTP ${response.status}，${contentType || '未知格式'}），请刷新页面后重试`);
  }
  const data = await response.json();
  const headerBalance = response.headers.get('X-Points-Balance');
  if (headerBalance !== null) setWalletBalance(Number(headerBalance));
  if (response.status === 401) showAuth();
  if (!response.ok) throw new Error(data.detail || data.message || `请求失败（HTTP ${response.status}）`);
  return data;
}

function setWalletBalance(balance) {
  currentWallet.balance = Number(balance || 0);
  const top = document.querySelector('#wallet-balance');
  const modal = document.querySelector('#wallet-modal-balance');
  if (top) top.textContent = number(currentWallet.balance);
  if (modal) modal.textContent = number(currentWallet.balance);
}

function renderWallet(wallet = {}) {
  currentWallet = { ...currentWallet, ...wallet };
  setWalletBalance(currentWallet.balance);
  document.querySelector('#wallet-trial').textContent = number(currentWallet.trial);
  document.querySelector('#wallet-bonus').textContent = number(currentWallet.bonus);
  document.querySelector('#wallet-paid').textContent = number(currentWallet.paid);
}

function showAuth() {
  if (authModal) authModal.hidden = false;
}

function hideAuth() {
  if (authModal) authModal.hidden = true;
}

function setAuthMode(mode) {
  const register = mode === 'register';
  document.querySelectorAll('[data-auth-mode]').forEach(button => button.classList.toggle('active', button.dataset.authMode === mode));
  document.querySelector('#display-name-field').hidden = !register;
  document.querySelector('#auth-title').textContent = register ? '创建你的创作账号' : '登录你的创作工作台';
  document.querySelector('#auth-submit').textContent = register ? '注册并进入工作台' : '登录';
  document.querySelector('#auth-password').autocomplete = register ? 'new-password' : 'current-password';
  document.querySelector('#auth-form').dataset.mode = mode;
  document.querySelector('#auth-error').hidden = true;
}

document.querySelectorAll('[data-auth-mode]').forEach(button => button.addEventListener('click', () => setAuthMode(button.dataset.authMode)));

document.querySelector('#auth-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const mode = event.currentTarget.dataset.mode || 'login';
  const submit = document.querySelector('#auth-submit');
  const error = document.querySelector('#auth-error');
  const finish = beginButton(submit, mode === 'register' ? '正在注册…' : '正在登录…');
  try {
    const response = await fetch(`/api/auth/${mode}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: document.querySelector('#auth-email').value.trim(),
        password: document.querySelector('#auth-password').value,
        display_name: document.querySelector('#auth-display-name').value.trim(),
      }),
    });
    const data = await readApiResponse(response);
    currentAccount = data.user;
    syncAdminVisibility();
    renderWallet(data.wallet);
    document.querySelector('#wallet-user-line').textContent = `${currentAccount.display_name} · ${currentAccount.email}`;
    document.querySelector('.api-live-dot')?.classList.remove('offline');
    hideAuth();
    showToast(mode === 'register' ? '账号创建成功' : '登录成功');
  } catch (exception) {
    error.textContent = exception.message;
    error.hidden = false;
  } finally { finish(); }
});

function renderTransactions(items = []) {
  const root = document.querySelector('#wallet-transactions');
  if (!items.length) { root.innerHTML = '<p>暂无积分记录</p>'; return; }
  root.innerHTML = items.map(item => `<article><span class="transaction-icon ${item.amount > 0 ? 'in' : 'out'}"><i data-lucide="${item.amount > 0 ? 'plus' : 'sparkles'}"></i></span><div><strong>${esc(item.feature || item.note || (item.amount > 0 ? '积分充值' : '功能消费'))}</strong><small>${esc(item.note || item.source)} · ${new Date(item.created_at).toLocaleString('zh-CN')}</small></div><b class="${item.amount > 0 ? 'in' : 'out'}">${item.amount > 0 ? '+' : ''}${number(item.amount)}</b></article>`).join('');
  window.lucide?.createIcons();
}

async function refreshWallet(open = false) {
  if (!currentAccount) return;
  const response = await fetch('/api/wallet');
  const data = await readApiResponse(response);
  renderWallet(data.wallet);
  renderTransactions(data.transactions);
  if (open) walletModal.hidden = false;
}

async function openWallet() {
  toggleSettingsMenu(false);
  try {
    await refreshWallet(true);
    const isOwnerAdmin = currentAccount?.role === 'admin' && currentAccount?.email?.toLowerCase() === 'gelen5@163.com';
    if (isOwnerAdmin) {
      document.querySelector('#admin-recharge-panel').hidden = false;
      await searchAdminUsers();
    }
  } catch (error) { showToast(error.message, 'error'); }
}

async function searchAdminUsers() {
  if (currentAccount?.role !== 'admin') return;
  const query = encodeURIComponent(document.querySelector('#admin-user-query').value.trim());
  const response = await fetch(`/api/admin/users?query=${query}`);
  const data = await readApiResponse(response);
  const root = document.querySelector('#admin-user-results');
  root.innerHTML = data.users.map(user => `<button type="button" data-admin-user="${esc(user.id)}" data-admin-name="${esc(user.display_name)}" data-admin-email="${esc(user.email)}"><span><strong>${esc(user.display_name)}</strong><small>${esc(user.email)}</small></span><b>${number(user.balance)} 分</b></button>`).join('') || '<p>没有找到用户</p>';
  root.querySelectorAll('[data-admin-user]').forEach(button => button.addEventListener('click', () => {
    document.querySelector('#admin-user-id').value = button.dataset.adminUser;
    document.querySelector('#admin-selected-user').textContent = `正在给 ${button.dataset.adminName}（${button.dataset.adminEmail}）充值`;
    document.querySelector('#admin-recharge-form').hidden = false;
  }));
}

document.querySelector('#admin-user-query')?.addEventListener('input', () => {
  clearTimeout(window.adminSearchTimer);
  window.adminSearchTimer = setTimeout(searchAdminUsers, 250);
});

document.querySelector('#admin-recharge-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button[type="submit"]');
  const finish = beginButton(button, '正在充值…');
  try {
    const response = await fetch('/api/admin/recharge', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: document.querySelector('#admin-user-id').value,
        points: Number(document.querySelector('#admin-points').value),
        bucket: document.querySelector('#admin-bucket').value,
        note: document.querySelector('#admin-note').value.trim(),
      }),
    });
    await readApiResponse(response);
    showToast('积分充值成功');
    document.querySelector('#admin-note').value = '';
    await searchAdminUsers();
    await refreshWallet();
  } catch (error) { showToast(error.message, 'error'); } finally { finish(); }
});

walletSettingsButton?.addEventListener('click', openWallet);
document.querySelector('#wallet-chip')?.addEventListener('click', openWallet);
document.querySelector('#wallet-close')?.addEventListener('click', () => { walletModal.hidden = true; });
document.querySelector('#wallet-refresh')?.addEventListener('click', () => refreshWallet());
walletModal?.addEventListener('click', event => { if (event.target === walletModal) walletModal.hidden = true; });
logoutButton?.addEventListener('click', async () => {
  await fetch('/api/auth/logout', { method: 'POST' });
  currentAccount = null;
  syncAdminVisibility();
  renderWallet({ balance: 0, trial: 0, bonus: 0, paid: 0 });
  walletModal.hidden = true;
  showAuth();
});

async function loadAccount() {
  try {
    const response = await fetch('/api/auth/me');
    if (!response.ok) { showAuth(); return; }
    const data = await readApiResponse(response);
    currentAccount = data.user;
    syncAdminVisibility();
    renderWallet(data.wallet);
    document.querySelector('#wallet-user-line').textContent = `${currentAccount.display_name} · ${currentAccount.email}`;
    document.querySelector('.api-live-dot')?.classList.remove('offline');
  } catch { showAuth(); }
}

function toggleSettingsMenu(force) {
  const next = typeof force === 'boolean' ? force : settingsMenu.hidden;
  settingsMenu.hidden = !next;
  settingsButton?.setAttribute('aria-expanded', String(next));
}

async function openApiSettings() {
  if (apiSettingsButton?.hidden) return;
  toggleSettingsMenu(false);
  try {
    const data = await readApiResponse(await fetch('/api/admin/provider-settings'));
    const settings = data.settings || {};
    sharedTextKeyInput.value = '';
    sharedImageKeyInput.value = '';
    sharedTextBaseUrlInput.value = settings.text_base_url || 'https://huoxingapi.com/v1';
    sharedImageBaseUrlInput.value = settings.image_base_url || 'https://img.rjm.us.ci';
    sharedTextModelInput.value = settings.text_model || 'deepseek-v4-flash';
    sharedImageModelInput.value = settings.image_model || 'gpt-image-2';
    textConfigStatus.textContent = settings.text_configured ? '已配置' : '未配置';
    imageConfigStatus.textContent = settings.image_configured ? '已配置' : '未配置';
    textConfigStatus.classList.toggle('ready', Boolean(settings.text_configured));
    imageConfigStatus.classList.toggle('ready', Boolean(settings.image_configured));
    apiSettingsModal.hidden = false;
    sharedTextKeyInput.focus();
  } catch (error) { showToast(error.message, 'error'); }
}

function closeApiSettings() {
  apiSettingsModal.hidden = true;
}

async function saveApiSettings() {
  try {
    const response = await fetch('/api/admin/provider-settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
      text_api_key: cleanApiKey(sharedTextKeyInput.value), image_api_key: cleanApiKey(sharedImageKeyInput.value),
      text_base_url: sharedTextBaseUrlInput.value.trim(), image_base_url: sharedImageBaseUrlInput.value.trim(),
      text_model: sharedTextModelInput.value.trim(), image_model: sharedImageModelInput.value.trim(),
    }) });
    await readApiResponse(response);
    closeApiSettings();
    showToast('API 配置已安全保存到服务器');
  } catch (error) { showToast(error.message, 'error'); }
}

settingsButton?.addEventListener('click', (event) => {
  event.stopPropagation();
  toggleSettingsMenu();
});
apiSettingsButton?.addEventListener('click', openApiSettings);
adminUsersButton?.addEventListener('click', openAdminUsers);
document.querySelector('#admin-users-close')?.addEventListener('click', () => { adminUsersModal.hidden = true; });
document.querySelector('#admin-users-refresh')?.addEventListener('click', () => loadAdminUsers(document.querySelector('#admin-users-search').value.trim()));
document.querySelector('#admin-users-search')?.addEventListener('input', event => { clearTimeout(window.adminUsersTimer); window.adminUsersTimer = setTimeout(() => loadAdminUsers(event.target.value.trim()), 250); });
document.querySelector('#admin-tasks-refresh')?.addEventListener('click', () => loadAdminTasks().catch(error => showToast(error.message, 'error')));
document.querySelector('#stop-impersonation')?.addEventListener('click', stopImpersonation);
document.querySelector('#api-settings-close')?.addEventListener('click', closeApiSettings);
document.querySelector('#api-settings-save')?.addEventListener('click', saveApiSettings);
function modalApiPayload() {
  return {
    textApiKey: cleanApiKey(sharedTextKeyInput.value),
    imageApiKey: cleanApiKey(sharedImageKeyInput.value),
    textBaseUrl: sharedTextBaseUrlInput.value.trim(),
    imageBaseUrl: sharedImageBaseUrlInput.value.trim(),
    textModel: sharedTextModelInput.value.trim(),
    imageModel: sharedImageModelInput.value.trim(),
  };
}

async function testProvider(kind, button) {
  const original = button.innerHTML;
  button.disabled = true;
  button.textContent = '正在测试…';
  try {
    const response = await fetch('/api/providers/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind }) });
    const data = await readApiResponse(response);
    const target = kind === 'text' ? textConfigStatus : imageConfigStatus;
    target.textContent = '连接成功';
    target.classList.add('ready');
    showToast(data.message || `${kind === 'text' ? '文字' : '图片'}连接成功`);
  } catch (error) {
    const target = kind === 'text' ? textConfigStatus : imageConfigStatus;
    target.textContent = '连接失败';
    target.classList.remove('ready');
    showToast(error.message, 'error');
  } finally {
    button.disabled = false;
    button.innerHTML = original;
    window.lucide?.createIcons();
  }
}

document.querySelector('#test-text-provider')?.addEventListener('click', event => testProvider('text', event.currentTarget));
document.querySelector('#test-image-provider')?.addEventListener('click', event => testProvider('image', event.currentTarget));
apiSettingsModal?.addEventListener('click', (event) => {
  if (event.target === apiSettingsModal) closeApiSettings();
});
document.addEventListener('click', (event) => {
  if (!event.target.closest?.('.settings-wrap')) toggleSettingsMenu(false);
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
  setActiveView('report');
  appShell?.classList.remove('landing');
  appShell?.classList.add('has-report');
  document.title = `${header['账号名'] || '公众号'} · 诊断报告`;
}

form?.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  button.querySelector('span').textContent = '…';
  try {
    const data = await submitQueuedTask('diagnose', { account_name: input.value.trim() });
    renderReport(data.report);
    reportRoot.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    alert(error.message);
  } finally { button.disabled = false; button.querySelector('span').textContent = '↗'; }
});

downloadButton?.addEventListener('click', () => window.print());

// Content workbench: a thin, stateful UI over the installed Skill adapter.
const workbench = document.querySelector('#workbench');
const homePage = document.querySelector('#home');
const diagnosePage = document.querySelector('#diagnose');
const modeButtons = [...document.querySelectorAll('.mode-option')];
const workflowSteps = document.querySelector('#workflow-steps');
const topicInput = document.querySelector('#workbench-topic');
const startWorkbench = document.querySelector('#start-workbench');
const workbenchResult = document.querySelector('#workbench-result');
const topicList = document.querySelector('#topic-list');
const articleEditor = document.querySelector('#article-editor');
const generatedImages = document.querySelector('#generated-images');
const decisionPanel = document.querySelector('#workbench-decision');
const runNextButton = document.querySelector('#run-next');
const previewButton = document.querySelector('#open-preview');
const workbenchProgress = document.querySelector('#workbench-progress');
const workbenchProgressTitle = document.querySelector('#workbench-progress-title');
const workbenchProgressDetail = document.querySelector('#workbench-progress-detail');
const workbenchProgressBar = document.querySelector('#workbench-progress-bar');
const cancelWorkbenchButton = document.querySelector('#cancel-workbench');
let workbenchController = null;
let workbenchTaskId = null;
const editCurrentButton = document.querySelector('#edit-current');
let workbenchMode = 'interactive';
let workbenchSession = null;
let workbenchVersionIndex = -1;

const stepGuidance = {
  1: { label: '选择选题', title: '从下面的方向里，选一个你愿意写下去的。', detail: '选择后才会生成文章框架，不会直接生成整篇文章。', action: '选择方向后生成框架', next: '生成文章框架' },
  2: { label: '确认框架', title: '先看文章怎么展开，再决定是否写正文。', detail: '确认后会生成一篇可直接编辑的完整初稿。', action: '确认框架，生成初稿', next: '生成完整初稿' },
  3: { label: '编辑初稿', title: '这是你的文章初稿，可以直接改成自己的表达。', detail: '确认后才进入反 AI 审校；请先补充个人经历、事实或具体判断。', action: '确认正文，开始审校', next: '反 AI 审校' },
  4: { label: '确认文字', title: '文字审校完成，请检查语气和事实边界。', detail: '确认后会依据文章内容生成封面与正文配图。', action: '确认文字，生成配图', next: '生成两张配图' },
  5: { label: '确认配图', title: '封面和正文图已经就绪，确认它们是否服务文章。', detail: '确认后会调用排版 Skill，生成可复制到公众号的富文本。', action: '确认配图，开始排版', next: 'Skill 排版' },
  6: { label: '生成预览', title: '排版已完成，下一步查看公众号实际粘贴效果。', detail: '预览页支持一键复制富文本，也可以下载 HTML 存档。', action: '打开预览并复制', next: '公众号富文本预览' },
  7: { label: '交付内容', title: '内容已经可以交付到公众号后台。', detail: '复制或下载 HTML 后粘贴到公众号；确认无误再写入草稿箱。', action: '写入公众号草稿箱', next: '写入草稿箱' },
  8: { label: '发布完成', title: '草稿写入流程已完成。', detail: '你仍可返回正文修改，并重新生成预览。', action: '完成', next: '—' },
};

function renderScoreReport(session) {
  const wrap = document.querySelector('#score-report');
  if (!wrap) return;
  const scoreObj = session?.score;
  const score = scoreObj?.score;
  if (score == null) { wrap.hidden = true; wrap.innerHTML = ''; return; }
  const val = Number(score);
  const ok = val >= 80;
  const pct = Math.round(Math.max(0, Math.min(100, val)));
  const dims = scoreObj?.dimensions || scoreObj?.scores || null;
  const dimRows = dims ? Object.entries(dims).filter(([, v]) => v != null).map(([k, v]) => {
    const nv = Math.round(Math.max(0, Math.min(100, Number(v))));
    return `<div class="srow"><span>${esc(k)}</span><div class="sbar"><i style="width:${nv}%"></i></div><em>${nv}</em></div>`;
  }).join('') : '';
  const fixes = session.suggestions && session.suggestions.length
    ? `<div class="score-fixes-head"><span class="micro-label">优先修改</span><h4>按建议改稿后重新审校</h4></div><ul class="score-fixes">${session.suggestions.slice(0, 6).map(x => `<li>${esc(typeof x === 'string' ? x : (x.text || x.title || ''))}</li>`).join('')}</ul>` : '';
  wrap.hidden = false;
  wrap.innerHTML = `<section class="score-report-card">
    <div class="score-ring" style="--p:${pct}"><div><strong>${val}</strong><span>结构参考</span></div></div>
    <div class="score-body">
      <header><span class="score-badge ${ok ? 'ok' : 'revise'}">${ok ? '可以发布' : '修改后复核'}</span><h3>反 AI 审校报告</h3><p>${esc(scoreObj.summary || (ok ? '表达与结构达到可发布标准。' : '发现可优化的表达与事实边界，建议按清单调整。'))}</p></header>
      ${dimRows ? `<div class="score-dims">${dimRows}</div>` : ''}
      ${fixes}
    </div>
  </section>`;
  window.lucide?.createIcons();
}

function renderDecisionPanel(session) {
  if (!session) {
    // 初次进入：保留 #workbench-decision 静态模板卡（不要 innerHTML 清空）
    const flowLabel = document.querySelector('#flow-step-label');
    const flowHint = document.querySelector('#flow-step-hint');
    if (flowLabel) flowLabel.textContent = '等待你的想法';
    if (flowHint) flowHint.textContent = '从三个方向里挑一个，或直接说你的选题';
    runNextButton.innerHTML = '<i data-lucide="arrow-right"></i> 先选择一个方向';
    runNextButton.disabled = true;
    previewButton.hidden = true;
    document.querySelector('#publish-draft').hidden = true;
    return;
  }
  const step = session.current_step || 1;
  const guide = stepGuidance[step] || stepGuidance[1];
  decisionPanel.innerHTML = `<span>正在做</span><strong>${esc(guide.label)}</strong><p>${esc(guide.title)}</p>`;
  const flowLabel = document.querySelector('#flow-step-label');
  const flowHint = document.querySelector('#flow-step-hint');
  if (flowLabel) flowLabel.textContent = `第 ${step} 步 · ${guide.label}`;
  if (flowHint) flowHint.textContent = guide.detail;
  runNextButton.innerHTML = `<i data-lucide="arrow-right"></i> ${step === 1 ? '先选择一个方向' : `下一步：${guide.action}`}`;
  runNextButton.disabled = step === 1;
  runNextButton.hidden = step >= 7;
  previewButton.hidden = !(session.preview_url || step >= 7);
  document.querySelector('#publish-draft').hidden = step < 7;
}

function paintWorkflow(current = 1) {
  const steps = ['选题', '框架', '写作', '反 AI', '配图', '排版', '预览', '发布'];
  const notes = { 1: '找到值得写的方向', 2: '确定文章骨架', 3: '形成完整初稿', 4: '检查 AI 痕迹', 5: '规划视觉表达', 6: '生成公众号排版', 7: '手机端预览效果', 8: '确认后进入草稿箱' };
  workflowSteps.innerHTML = steps.map((name, index) => {
    const n = index + 1;
    const state = n < current ? 'done' : n === current ? 'active' : '';
    const clickable = n < current ? 'clickable' : '';
    return `<button type="button" class="workflow-step ${state} ${clickable}" data-step="${n}" ${n === current ? 'aria-current="step"' : ''} ${n > current ? 'tabindex="-1"' : ''}><span>${String(n).padStart(2, '0')}</span><div><strong>${name}</strong><small>${notes[n]}</small></div></button>`;
  }).join('');
  workflowSteps.querySelectorAll('.workflow-step.clickable').forEach(el => {
    el.addEventListener('click', () => reviewStep(Number(el.dataset.step)));
  });
}

function flashProduct(id, message) {
  const el = document.getElementById(id);
  const hint = document.querySelector('#flow-step-hint');
  if (hint && message) hint.textContent = message;
  if (!el) return;
  if (el.hidden) el.hidden = false;
  el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  el.classList.add('flash-ring');
  setTimeout(() => el.classList.remove('flash-ring'), 1400);
}

function reviewStep(n) {
  const s = workbenchSession;
  if (!s) return;
  const label = ['', '选题方向', '文章结构', '当前正文', '反 AI 审校报告', '配图', '排版富文本', '预览页', '当前正文'][n] || '第 ' + n + ' 步产物';
  switch (n) {
    case 2: flashProduct('workbench-outline', `已回到第 ${n} 步 · ${label}`); break;
    case 3: case 8: flashProduct('article-editor', `已回到第 ${n} 步 · ${label}`); break;
    case 4: renderScoreReport(s); flashProduct('score-report', `已回到第 ${n} 步 · ${label}`); break;
    case 5: flashProduct('generated-images', `已回到第 ${n} 步 · ${label}`); break;
    case 6:
      if (s.html_download_url) { flashProduct('article-editor', '第 6 步产物 · 排版富文本已生成，可在底部下载 HTML'); }
      else { const hint = document.querySelector('#flow-step-hint'); if (hint) hint.textContent = '该步产物尚未生成，继续推进后即可回看'; }
      break;
    case 7:
      if (s.preview_url) window.open(s.preview_url, '_blank');
      else { const hint = document.querySelector('#flow-step-hint'); if (hint) hint.textContent = '预览尚未生成，先推进排版步骤'; }
      break;
  }
}

function renderChatThread(session) {
  const thread = document.querySelector('#workbench-chat-thread');
  if (!thread) return;
  const history = session?.conversation || [];
  const seed = !workbenchSession ? [{ role: 'assistant', content: '你好，我是你的公众号共创助手。告诉我一个想法、一个问题，或者一条想写却没想清楚的内容。' }] : history;
  thread.innerHTML = seed.length ? seed.map(item => `<article class="chat-message ${item.role === 'user' ? 'from-user' : 'from-ai'}"><span>${item.role === 'user' ? '你' : 'AI 共创助手'}</span><p>${esc(item.content)}</p></article>`).join('') : `<article class="chat-message from-ai"><span>AI 共创助手</span><p>我已准备好。你可以选一个方向，也可以说说哪里不满意。</p></article>`;
  thread.scrollTop = thread.scrollHeight;
}

function renderOutline(session) {
  const outline = document.querySelector('#workbench-outline');
  const items = session.framework?.outline || [];
  outline.innerHTML = items.length ? items.map((item, index) => `<li><span>${String(index + 1).padStart(2, '0')}</span><p>${esc(item)}</p></li>`).join('') : `<li><span>01</span><p>先从对话里确认值得写的角度</p></li>`;
  const versions = document.querySelector('#workbench-version-list');
  const source = session.versions || [];
  versions.innerHTML = `${source.slice(-3).reverse().map((item, index) => `<button class="version-item" data-version-index="${source.length - 1 - index}" type="button"><strong>${esc(item.label)}</strong><span>${esc(item.summary)}</span></button>`).join('')}<button class="version-item current" data-version-index="current" type="button"><strong>当前</strong><span>${esc(session.last_change || '刚刚生成')}</span></button>`;
  versions.querySelectorAll('.version-item').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.versionIndex === 'current') { workbenchVersionIndex = -1; articleEditor.value = session.article || ''; return; }
    const picked = source[Number(button.dataset.versionIndex)];
    if (picked) { workbenchVersionIndex = Number(button.dataset.versionIndex); articleEditor.value = picked.article || ''; document.querySelector('#article-version-label').textContent = `${picked.label} · 历史版本预览`; }
  }));
}

function renderWorkbenchSession(session) {
  workbenchSession = session;
  workbenchResult.hidden = false;
  workbenchVersionIndex = -1;
  paintWorkflow(session.current_step || 1);
  const statusLabels = { calling_text_api: '文本 API 生成中', calling_image_api: '图片 API 生成中', rendering: '正在排版', awaiting_topic: '等待选择', ready_for_review: '等待确认', complete: '已完成', running: `第 ${session.current_step || 1} 步` };
  document.querySelector('#workbench-status').textContent = statusLabels[session.status] || `第 ${session.current_step || 1} 步`;
  document.querySelector('#result-title').textContent = session.topic || '正在等你说第一句话';
  document.querySelector('#article-save-state').textContent = session.article ? '草稿 · 已保存到当前会话' : '正在确认写作方向';
  document.querySelector('#article-version-label').textContent = session.article ? `当前版本 · ${session.versions?.length ? `V${session.versions.length + 1}` : 'V1'}` : '当前草稿 · 尚未生成';
  document.querySelector('#article-change-label').textContent = session.last_change || '等待你确认写作方向';
  renderDecisionPanel(session);
  renderChatThread(session);
  articleEditor.value = session.article || '';
  const score = session.score?.score;
  renderScoreReport(session);
  document.querySelector('#score-label').textContent = score == null ? '反 AI 评分将在第 4 步生成' : `反 AI 综合评分 ${Number(score).toFixed(1)} · 详细报告见下方审校卡`;
  const textModel = session.provider?.text?.model || '文本模型';
  const imageModel = session.provider?.image?.model || '图片模型';
  document.querySelector('#result-meta').textContent = session.framework ? `${session.framework.name} 框架 · ${session.persona || '默认人格'} · 文本 ${textModel} · 图片 ${imageModel}` : `选题由 ${textModel} 实时生成`;
  const htmlDownload = document.querySelector('#download-workbench-html');
  if (htmlDownload) {
    htmlDownload.hidden = !session.html_download_url;
    htmlDownload.href = session.html_download_url || '#';
  }
  const suggestions = session.suggestions || [];
  topicList.innerHTML = session.current_step === 1 && suggestions.length ? `<div class="chat-choice-head"><strong>我先给你三个写法方向</strong><span>可采用，也可继续让我调整</span></div>${suggestions.slice(0, 3).map(item => `<article class="chat-choice"><span>${String(item.id).padStart(2, '0')}</span><div><strong>${esc(item.title)}</strong><p>${esc(item.reason)}</p><small>${esc(item.type)}</small></div><footer><button class="adopt-topic" data-topic-id="${item.id}" type="button">采用</button><button class="regenerate-topic" type="button">重新生成</button></footer></article>`).join('')}` : '';
  topicList.querySelectorAll('.adopt-topic').forEach(item => item.addEventListener('click', async () => { await advance(Number(item.dataset.topicId), 2); renderChatThread(workbenchSession); }));
  topicList.querySelectorAll('.regenerate-topic').forEach(item => item.addEventListener('click', () => sendWorkbenchChat('这个方向不错，但请换一个更有冲突和具体场景的写法。', 'regenerate_topics')));
  renderOutline(session);
  window.lucide?.createIcons();
  const images = session.images || [];
  generatedImages.hidden = !images.length;
  const remoteImages = images.filter(image => image.delivery === 'remote').length;
  generatedImages.innerHTML = images.length ? `<div class="image-section-head"><div><span class="micro-label">API 生成配图</span><h3>封面与正文配图</h3></div><span>${images.length} 张 · ${remoteImages ? `${remoteImages} 张由供应商 CDN 提供` : '已自动压缩至微信限制内'}</span></div><div class="image-grid">${images.map(image => `<a href="${esc(image.url)}" target="_blank" rel="noopener"><img src="${esc(image.url)}" alt="${image.kind === 'cover' ? '文章封面' : '正文配图'}" /><span><strong>${image.kind === 'cover' ? '文章封面' : '正文配图'}</strong><small>${esc(image.model)} · ${image.delivery === 'remote' ? '外链预览' : `${Math.round(Number(image.bytes || 0) / 1024)} KB`}</small></span></a>`).join('')}</div>` : '';
}

function setWorkbenchProgress(target, active = true, message = '') {
  if (!workbenchProgress) return;
  workbenchProgress.hidden = !active;
  if (!active) return;
  const labels = { 2: '正在生成文章框架', 3: '正在生成完整初稿', 4: '正在进行反 AI 审校', 5: '正在生成封面与正文配图', 6: '正在生成公众号排版', 7: '正在生成手机端预览' };
  const details = { 2: '先确认文章怎么展开', 3: '文字模型正在组织正文', 4: '检查表达、事实边界和可读性', 5: '图片生成可能需要数分钟，请勿重复点击', 6: '把正文和图片整理成可复制内容', 7: '生成最终可查看、可下载的文件' };
  workbenchProgressTitle.textContent = message || labels[target] || '正在处理';
  workbenchProgressDetail.textContent = details[target] || '请稍候';
  workbenchProgressBar.style.width = `${Math.max(8, Math.min(96, target / 8 * 100))}%`;
  runNextButton.disabled = true;
}

async function callWorkbench(path, payload, signal) {
  if (path === '/api/workbench/steps' && Number(payload.step) >= 5) {
    const result = await submitQueuedTask('workbench_step', {
      session_id: payload.session_id,
      step: payload.step,
      selection: payload.selection,
      article: payload.article,
    }, signal, job => { workbenchTaskId = job.id; });
    workbenchTaskId = null;
    return result.session;
  }
  const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...sharedApiPayload(), ...payload }), signal });
  const data = await readApiResponse(response);
  return data.session;
}

function newIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.() || `workbench-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function waitForWorkbenchJob(jobId) {
  for (;;) {
    const data = await readApiResponse(await fetch(`/api/workbench/jobs/${encodeURIComponent(jobId)}`));
    const job = data.job || {};
    document.querySelector('#workbench-status').textContent = job.status === 'queued' ? '任务排队中' : 'Skill 执行中';
    if (job.status === 'completed' && data.session) return data.session;
    if (job.status === 'failed') throw new Error(job.error || '创作任务失败，积分已自动退还');
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
}

async function advance(selection = null, nextStep = null) {
  if (!workbenchSession) return;
  const target = nextStep || Math.min(8, (workbenchSession.current_step || 1) + 1);
  workbenchController = new AbortController();
  setWorkbenchProgress(target);
  try {
    workbenchSession = await callWorkbench('/api/workbench/steps', { session_id: workbenchSession.id, step: target, selection, article: articleEditor.value }, workbenchController.signal);
    renderWorkbenchSession(workbenchSession);
  } finally {
    setWorkbenchProgress(target, false);
    workbenchController = null;
  }
}

modeButtons.forEach(button => button.addEventListener('click', () => { modeButtons.forEach(item => item.classList.remove('active')); button.classList.add('active'); workbenchMode = button.dataset.mode; }));
startWorkbench?.addEventListener('click', async () => {
  const message = topicInput.value.trim();
  if (!message) { topicInput.focus(); return; }
  if (workbenchSession) { await sendWorkbenchChat(message); return; }
  startWorkbench.disabled = true;
  const originalLabel = startWorkbench.innerHTML;
  startWorkbench.innerHTML = '任务提交中…';
  try {
    const response = await fetch('/api/workbench/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...sharedApiPayload(), topic: message, mode: workbenchMode, persona: document.querySelector('#workbench-persona').value, theme: document.querySelector('#workbench-theme').value, idempotency_key: newIdempotencyKey() }) });
    const accepted = await readApiResponse(response);
    startWorkbench.innerHTML = 'Skill 执行中…';
    const session = await waitForWorkbenchJob(accepted.job.id);
    renderWorkbenchSession(session);
    topicInput.value = '';
  } catch (error) { alert(error.message); } finally { startWorkbench.disabled = false; startWorkbench.innerHTML = originalLabel; }
});
async function sendWorkbenchChat(message, action = 'rewrite_article', selectionText = '') {
  if (!workbenchSession) return;
  const send = startWorkbench;
  send.disabled = true;
  const original = send.textContent;
  send.textContent = '…';
  try {
    const session = await callWorkbench('/api/workbench/chat', { session_id: workbenchSession.id, message, action, selection_text: selectionText });
    renderWorkbenchSession(session);
    topicInput.value = '';
  } catch (error) { alert(error.message); } finally { send.disabled = false; send.textContent = original || '↑'; }
}

runNextButton?.addEventListener('click', async () => {
  if (!workbenchSession) return;
  const current = workbenchSession.current_step || 1;
  if (current < 2 || current >= 7) return;
  runNextButton.disabled = true;
  try { await advance(null, current + 1); } catch (error) { if (error.name !== 'AbortError') alert(error.message); } finally { runNextButton.disabled = false; }
});
cancelWorkbenchButton?.addEventListener('click', async () => {
  if (!workbenchSession || !workbenchController) return;
  cancelWorkbenchButton.disabled = true;
  try {
    if (workbenchTaskId) {
      await fetch(`/api/tasks/${encodeURIComponent(workbenchTaskId)}/cancel`, { method: 'POST' });
    } else {
      await fetch('/api/workbench/cancel', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...sharedApiPayload(), session_id: workbenchSession.id, step: workbenchSession.current_step || 1 }) });
    }
  } finally {
    workbenchController.abort();
    workbenchProgressTitle.textContent = '已取消等待';
    workbenchProgressDetail.textContent = '服务器会在当前图片请求结束后停止后续生成，请稍后刷新会话状态。';
    workbenchProgressBar.style.width = '0%';
    cancelWorkbenchButton.disabled = false;
  }
});
document.querySelector('#workbench-regenerate-topics')?.addEventListener('click', () => { if (workbenchSession) sendWorkbenchChat('请重新给我三个方向，角度更具体，不要泛泛而谈。', 'regenerate_topics'); else topicInput.focus(); });
document.querySelector('#new-workbench-chat')?.addEventListener('click', () => { workbenchSession = null; workbenchVersionIndex = -1; topicInput.value = ''; articleEditor.value = ''; document.querySelector('#result-title').textContent = '还没有开始写'; document.querySelector('#article-save-state').textContent = '输入一个主题后，我会先和你确认写作方向'; document.querySelector('#article-version-label').textContent = '当前草稿 · 尚未生成'; document.querySelector('#article-change-label').textContent = '等待你的写作意图'; document.querySelector('#workbench-status').textContent = '等待你的想法'; topicList.innerHTML = ''; renderChatThread(null); renderOutline({}); });
document.querySelectorAll('[data-rewrite-selection]').forEach(button => button.addEventListener('click', () => { if (!workbenchSession) return; const selection = articleEditor.value.slice(articleEditor.selectionStart, articleEditor.selectionEnd); if (!selection) { alert('先在当前文章中选中一段，再告诉我如何改写。'); return; } sendWorkbenchChat(button.dataset.rewriteSelection, 'rewrite_article', selection); }));
document.querySelector('#version-back')?.addEventListener('click', () => { const versions = workbenchSession?.versions || []; if (!versions.length) return; workbenchVersionIndex = workbenchVersionIndex < 0 ? versions.length - 1 : Math.max(0, workbenchVersionIndex - 1); articleEditor.value = versions[workbenchVersionIndex].article || ''; document.querySelector('#article-version-label').textContent = `${versions[workbenchVersionIndex].label} · 历史版本预览`; });
document.querySelector('#version-forward')?.addEventListener('click', () => { const versions = workbenchSession?.versions || []; if (workbenchVersionIndex < 0) return; workbenchVersionIndex += 1; if (workbenchVersionIndex >= versions.length) { workbenchVersionIndex = -1; articleEditor.value = workbenchSession.article || ''; document.querySelector('#article-version-label').textContent = `当前版本 · V${versions.length + 1}`; return; } articleEditor.value = versions[workbenchVersionIndex].article || ''; document.querySelector('#article-version-label').textContent = `${versions[workbenchVersionIndex].label} · 历史版本预览`; });
document.querySelector('#open-preview')?.addEventListener('click', async () => {
  if (!workbenchSession) return;
  try { const session = await callWorkbench('/api/workbench/preview', { session_id: workbenchSession.id, article: articleEditor.value }); renderWorkbenchSession(session); window.open(session.preview_url, '_blank', 'noopener'); } catch (error) { alert(error.message); }
});
document.querySelector('#publish-draft')?.addEventListener('click', async () => {
  if (!workbenchSession) return;
  try { const session = await callWorkbench('/api/workbench/publish', { session_id: workbenchSession.id, draft: true }); renderWorkbenchSession(session); alert(session.publish?.message || '已完成'); } catch (error) { alert(error.message); }
});
editCurrentButton?.addEventListener('click', () => { articleEditor?.scrollIntoView({ behavior: 'smooth', block: 'center' }); articleEditor?.focus(); });
articleEditor?.addEventListener('input', () => { if (workbenchSession) workbenchSession.article = articleEditor.value; });
renderChatThread(null);
renderOutline({});

async function postCreator(path, payload, signal) {
  const taskTypes = {
    '/api/xiaohongshu/package': 'xiaohongshu',
    '/api/tie-tu/plan': 'tie_tu',
    '/api/hit-detector/analyze': 'hit_detect',
    '/api/hit-detector/rewrite': 'hit_rewrite',
    '/api/creator-tools/image': 'creator_image',
  };
  if (taskTypes[path]) {
    const taskPayload = path === '/api/xiaohongshu/package' ? { topic: payload.topic, account: payload.account, audience: payload.audience, goal: payload.goal, evidence: payload.evidence, content_type: payload.contentType }
      : path === '/api/tie-tu/plan' ? { industry: payload.industry, topic: payload.topic, title: payload.title || '', content_type: payload.contentType || null, image_count: payload.imageCount, style: payload.style, audience: payload.audience, portrait_mode: payload.portraitMode }
      : path === '/api/hit-detector/analyze' ? { title: payload.title, body: payload.body, track: payload.track, fans: payload.fans, open_rate: payload.openRate }
      : path === '/api/hit-detector/rewrite' ? { title: payload.title, body: payload.body, detector_result: payload.detectorResult }
      : { tool: payload.tool, session_id: payload.sessionId, card: payload.card, style: payload.style };
    return submitQueuedTask(taskTypes[path], taskPayload, signal);
  }
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...sharedApiPayload(), ...payload }),
    signal,
  });
  return readApiResponse(response);
}

async function submitQueuedTask(type, payload, signal, onAccepted) {
  const accepted = await readApiResponse(await fetch('/api/tasks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type, idempotency_key: newIdempotencyKey(), payload }), signal }));
  const jobId = accepted.job?.id;
  if (!jobId) throw new Error('任务未返回编号');
  onAccepted?.(accepted.job);
  const cancel = () => fetch(`/api/tasks/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' }).catch(() => undefined);
  signal?.addEventListener('abort', cancel, { once: true });
  while (true) {
    try {
      await new Promise(resolve => setTimeout(resolve, 700));
      const state = await readApiResponse(await fetch(`/api/tasks/${encodeURIComponent(jobId)}`, { signal }));
      if (state.job.status === 'succeeded') return state.job.result;
      if (['failed', 'canceled'].includes(state.job.status)) throw new Error(state.job.error || '任务未完成');
    } finally {
      if (signal?.aborted) cancel();
    }
  }
}

function beginButton(button, label) {
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = `<span class="button-spinner"></span>${esc(label)}`;
  return () => { button.disabled = false; button.innerHTML = original; window.lucide?.createIcons(); };
}

function renderSkillProgress(root, total) {
  root.insertAdjacentHTML('afterbegin', `<div class="generation-progress"><div><strong>正在生成图片</strong><span class="progress-copy">0 / ${total}</span></div><div class="progress-track"><i style="width:0%"></i></div><button class="cancel-generation" type="button">取消</button></div>`);
  return root.querySelector('.generation-progress');
}

let imageGenerationController = null;
async function generateSkillImages(tool, sessionId, cards, style, grid) {
  imageGenerationController?.abort();
  imageGenerationController = new AbortController();
  const progress = renderSkillProgress(grid.parentElement, cards.length);
  progress.querySelector('.cancel-generation').addEventListener('click', () => imageGenerationController.abort());
  try {
    for (let index = 0; index < cards.length; index += 1) {
      const data = await postCreator('/api/creator-tools/image', { tool, sessionId, card: cards[index], style }, imageGenerationController.signal);
      const target = grid.querySelector(`[data-card-index="${data.image.index}"]`);
      if (target) {
        target.classList.add('generated');
        target.querySelector('.card-image-slot').innerHTML = `<img src="${esc(data.image.url)}" alt="第 ${data.image.index} 张生成图片"><a href="${esc(data.image.url)}" target="_blank" rel="noopener">查看原图</a>`;
      }
      const done = index + 1;
      progress.querySelector('.progress-copy').textContent = `${done} / ${cards.length}`;
      progress.querySelector('.progress-track i').style.width = `${done / cards.length * 100}%`;
    }
    progress.classList.add('done');
    progress.querySelector('strong').textContent = '图片生成完成';
    progress.querySelector('.cancel-generation').remove();
    showToast(`已生成 ${cards.length} 张图片`);
  } catch (error) {
    if (error.name === 'AbortError') {
      progress.querySelector('strong').textContent = '已取消生成';
      showToast('已取消后续图片生成', 'error');
    } else {
      progress.querySelector('strong').textContent = '生成中断';
      showToast(error.message, 'error');
    }
  } finally {
    imageGenerationController = null;
  }
}

function renderXhsPackage(pkg) {
  const root = document.querySelector('#xhs-result');
  document.querySelector('#xhs-empty').hidden = true;
  root.hidden = false;
  const titles = pkg.titles || [];
  const cards = pkg.cards || [];
  const precheck = pkg.precheck || {};
  root.innerHTML = `<div class="output-head"><div><span class="result-status ${esc(precheck.status || 'revise')}">${esc(precheck.status || 'revise')}</span><h2>${esc(pkg.selected_title || '小红书内容包')}</h2><p>${esc(pkg.angle || '')}</p></div><button id="xhs-images" class="secondary-action" type="button"><i data-lucide="images"></i>生成 6 张图片</button></div>
    <section class="result-section"><div class="result-section-title"><strong>标题方案</strong><span>3 个版本</span></div><div class="title-options">${titles.map((item, i) => `<article class="title-option ${i === 0 ? 'selected' : ''}"><span>0${i + 1}</span><div><strong>${esc(item.text)}</strong><small>${esc(item.keyword)} · ${esc(item.reason)}</small></div></article>`).join('')}</div></section>
    <section class="result-section"><div class="result-section-title"><strong>图文页面</strong><span>1 张封面 + 5 张内容页</span></div><div class="creator-card-grid">${cards.map(card => `<article class="creator-output-card" data-card-index="${Number(card.index)}"><div class="card-image-slot"><span>${String(card.index).padStart(2, '0')}</span><small>等待生成</small></div><div class="creator-card-copy"><span>${esc(card.role)}</span><strong>${esc(card.headline)}</strong><p>${esc(card.message)}</p><small>${esc(card.action)}</small></div></article>`).join('')}</div></section>
    <section class="result-section"><div class="result-section-title"><strong>发布文案</strong><button class="copy-result" data-copy-target="xhs-body" type="button"><i data-lucide="copy"></i>复制</button></div><textarea id="xhs-body" class="result-editor">${esc(pkg.body || '')}</textarea><div class="result-meta-grid"><div><span>置顶评论</span><p>${esc(pkg.pinned_comment || '')}</p></div><div><span>低压 CTA</span><p>${esc(pkg.cta || '')}</p></div></div></section>
    <section class="result-section"><div class="result-section-title"><strong>发布前检查</strong><span>${esc(precheck.status || '')}</span></div><ul class="issue-list">${(precheck.issues || []).map(item => `<li>${esc(item)}</li>`).join('') || '<li class="ok">未发现明确阻断项，进入人工终审。</li>'}</ul></section>`;
  root.querySelector('#xhs-images').addEventListener('click', () => generateSkillImages('xiaohongshu', pkg.session_id, cards, '真人贴纸爆款教程风，明亮蓝色创作者工作台，人物动作轮换', root.querySelector('.creator-card-grid')));
  bindCopyButtons(root);
  window.lucide?.createIcons();
}

document.querySelector('#xhs-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const button = document.querySelector('#xhs-generate');
  const finish = beginButton(button, '正在生成内容包…');
  try {
    const data = await postCreator('/api/xiaohongshu/package', {
      topic: document.querySelector('#xhs-topic').value.trim(),
      account: document.querySelector('#xhs-account').value.trim(),
      audience: document.querySelector('#xhs-audience').value.trim(),
      goal: document.querySelector('#xhs-goal').value,
      evidence: document.querySelector('#xhs-evidence').value.trim(),
      contentType: document.querySelector('#xhs-content-type').value,
    });
    renderXhsPackage(data.package);
  } catch (error) { showToast(error.message, 'error'); } finally { finish(); }
});

function renderTiePlan(plan) {
  const root = document.querySelector('#tie-result');
  document.querySelector('#tie-empty').hidden = true;
  root.hidden = false;
  const cards = plan.cards || [];
  root.innerHTML = `<div class="output-head"><div><span class="result-status pending">待确认计划</span><h2>${esc(plan.title)}</h2><p>${esc(plan.content_type_label)} · ${esc(plan.angle)}</p></div><button id="tie-images" class="primary-action compact" type="button"><i data-lucide="images"></i>确认并生成 ${cards.length} 张</button></div>
    <div class="plan-summary"><div><span>画幅</span><strong>${esc(plan.ratio)}</strong></div><div><span>图片</span><strong>${cards.length} 张</strong></div><div><span>人物一致性</span><strong>${plan.portrait_enabled ? '已启用' : '未启用'}</strong></div></div>
    <section class="result-section"><div class="result-section-title"><strong>卡片计划</strong><span>文字、动作和场景均可生成前检查</span></div><div class="creator-card-grid">${cards.map(card => `<article class="creator-output-card" data-card-index="${Number(card.index)}"><div class="card-image-slot"><span>${String(card.index).padStart(2, '0')}</span><small>等待生成</small></div><div class="creator-card-copy"><span>${esc(card.role)}</span><strong>${esc(card.overlay_text)}</strong><p>${esc(card.visual_subject)}</p><small>${esc(card.card_brief?.scene || '')} · ${esc(card.card_brief?.action || '')}</small></div></article>`).join('')}</div></section>
    <section class="result-section"><div class="result-section-title"><strong>配套文案</strong><button class="copy-result" data-copy-target="tie-copy" type="button"><i data-lucide="copy"></i>复制</button></div><textarea id="tie-copy" class="result-editor compact">${esc(plan.copy || '')}</textarea><p class="cta-line">${esc(plan.cta || '')}</p></section>`;
  root.querySelector('#tie-images').addEventListener('click', () => generateSkillImages('tie-tu', plan.session_id, cards, document.querySelector('#tie-style').value.trim(), root.querySelector('.creator-card-grid')));
  bindCopyButtons(root);
  window.lucide?.createIcons();
}

document.querySelector('#tie-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const button = document.querySelector('#tie-plan');
  const finish = beginButton(button, '正在策划卡片…');
  try {
    const data = await postCreator('/api/tie-tu/plan', {
      industry: document.querySelector('#tie-industry').value.trim(),
      topic: document.querySelector('#tie-topic').value.trim(),
      contentType: document.querySelector('#tie-content-type').value,
      imageCount: Number(document.querySelector('#tie-count').value),
      audience: document.querySelector('#tie-audience').value.trim(),
      style: document.querySelector('#tie-style').value.trim(),
      portraitMode: document.querySelector('#tie-portrait').value,
    });
    renderTiePlan(data.plan);
  } catch (error) { showToast(error.message, 'error'); } finally { finish(); }
});

function scoreRows(scores) {
  const names = { title: '标题', opening: '开头', content: '内容', structure: '结构', topic: '选题', readability: '阅读', visual: '视觉', interaction: '互动' };
  const full = { title: 18, opening: 16, content: 18, structure: 14, topic: 12, readability: 7, visual: 8, interaction: 7 };
  return Object.keys(names).map(key => `<div class="detector-score"><span>${names[key]}</span><div><i style="width:${Math.min(100, Number(scores[key] || 0) / full[key] * 100)}%"></i></div><strong>${Number(scores[key] || 0)}<small>/${full[key]}</small></strong></div>`).join('');
}

function renderHitReport(report) {
  const root = document.querySelector('#hit-result');
  document.querySelector('#hit-empty').hidden = true;
  root.hidden = false;
  const gate = report.editorial_gate || {};
  const suggestions = report.suggestions || [];
  root.innerHTML = `<div class="detector-hero"><div><span class="result-status ${gate.label === '暂缓发布' ? 'blocked' : gate.label === '修改后复核' ? 'revise' : 'ready'}">${esc(gate.label || '待复核')}</span><h2>${Number(report.scores?.total || 0)}</h2><p>结构参考分 / 100 · 不代表爆款概率</p></div><div class="detector-verdict"><strong>${esc(gate.summary || '')}</strong><p>${esc(report.track_name)} · ${esc(report.style_name)} · 置信度 ${esc(report.score_confidence)}</p><button id="hit-rewrite" class="secondary-action" type="button"><i data-lucide="file-pen-line"></i>按建议生成改稿</button></div></div>
    <section class="result-section"><div class="result-section-title"><strong>八维结构参考</strong><span>用于定位机械短板</span></div>${scoreRows(report.scores || {})}</section>
    <section class="result-section"><div class="result-section-title"><strong>优先修改</strong><span>P0 优先于总分</span></div><div class="suggestion-list">${suggestions.slice(0, 8).map(item => `<article><span>${esc(item.priority || item.level || 'P1')}</span><div><strong>${esc(item.title || item.issue || item.dimension || '编辑建议')}</strong><p>${esc(item.action || item.suggestion || item.detail || '')}</p></div></article>`).join('') || '<p class="muted-copy">当前没有生成额外建议，请进入人工终审。</p>'}</div></section>
    <section class="result-section"><div class="result-section-title"><strong>事实声明账本</strong><span>${(report.source_ledger || []).length} 条</span></div><div class="ledger-list">${(report.source_ledger || []).slice(0, 12).map(item => `<div><span>${esc(item.status || '待核验')}</span><p>${esc(item.claim || item.text || item.statement || item.title || JSON.stringify(item))}</p></div>`).join('') || '<p class="muted-copy">没有识别到需要单列的事实声明。</p>'}</div></section>`;
  root.querySelector('#hit-rewrite').addEventListener('click', async event => {
    const finish = beginButton(event.currentTarget, '正在改稿…');
    try {
      const data = await postCreator('/api/hit-detector/rewrite', { title: document.querySelector('#hit-title').value.trim(), body: document.querySelector('#hit-body').value, track: document.querySelector('#hit-track').value, detectorResult: report });
      document.querySelector('#hit-title').value = data.article.title;
      document.querySelector('#hit-body').value = data.article.body;
      showToast(data.article.change_summary || '改稿已回填，请再次复核');
    } catch (error) { showToast(error.message, 'error'); } finally { finish(); }
  });
  window.lucide?.createIcons();
}

document.querySelector('#hit-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const button = document.querySelector('#hit-analyze');
  const finish = beginButton(button, '正在复核文章…');
  try {
    const data = await postCreator('/api/hit-detector/analyze', {
      title: document.querySelector('#hit-title').value.trim(),
      body: document.querySelector('#hit-body').value,
      track: document.querySelector('#hit-track').value,
      fans: document.querySelector('#hit-fans').value ? Number(document.querySelector('#hit-fans').value) : null,
    });
    renderHitReport(data.report);
  } catch (error) { showToast(error.message, 'error'); } finally { finish(); }
});

function bindCopyButtons(root = document) {
  root.querySelectorAll('.copy-result').forEach(button => button.addEventListener('click', async () => {
    const target = document.getElementById(button.dataset.copyTarget);
    await navigator.clipboard.writeText(target?.value || target?.textContent || '');
    showToast('已复制到剪贴板');
  }));
}

const viewMap = {
  home: homePage,
  diagnose: diagnosePage,
  workbench,
  xiaohongshu: xiaohongshuPage,
  'tie-tu': tieTuPage,
  'hit-detector': hitDetectorPage,
  morning: morningGenerator,
  report: reportRoot,
};

const viewTitles = {
  home: '宇宙第一工作台',
  workbench: '公众号创作',
  xiaohongshu: '小红书创作',
  'tie-tu': '微信贴图号',
  'hit-detector': '爆文检测',
  morning: '早安祝福',
  report: '诊断报告',
};

function pathToView(path) {
  const p = String(path || '').replace(/^\/+|\/+$/g, '');
  if (!p) return 'home';
  if (p === 'morning-generator') return 'morning';
  return Object.prototype.hasOwnProperty.call(viewMap, p) ? p : 'home';
}

function setActiveView(view, updateHash = false) {
  Object.entries(viewMap).forEach(([name, element]) => { if (element) element.hidden = name !== view; });
  document.querySelectorAll('.app-tabs [data-view]').forEach(item => item.classList.toggle('active', item.dataset.view === view));
  appShell?.classList.toggle('workbench-active', view !== 'home' && view !== 'diagnose' && view !== 'report');
  if (downloadButton) downloadButton.hidden = view !== 'report';
  if (view === 'morning') syncMorningApiKey();
  const commandTitle = document.querySelector('#command-title');
  if (commandTitle) commandTitle.textContent = viewTitles[view] || '宇宙第一工作台';
  if (updateHash && view !== 'report') {
    const url = view === 'home' ? '/' : `/${view === 'morning' ? 'morning-generator' : view}`;
    history.replaceState(null, '', url);
  }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

document.querySelector('#command-settings')?.addEventListener('click', openWallet);

document.querySelectorAll('.app-tabs [data-view]').forEach(tab => tab.addEventListener('click', event => {
  event.preventDefault();
  setActiveView(tab.dataset.view, true);
}));

window.addEventListener('popstate', () => setActiveView(pathToView(location.pathname), false));

const initialView = pathToView(location.pathname);
setActiveView(initialView);
refreshConfigStatus();
paintWorkflow();
loadAccount();
window.lucide?.createIcons({ attrs: { 'stroke-width': 1.8 } });
