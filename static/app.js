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
const viralRemixPage = document.querySelector('#viral-remix');
const xhsExtractPage = document.querySelector('#xhs-extract');
const douyinExtractPage = document.querySelector('#douyin-extract');
const hitDetectorPage = document.querySelector('#hit-detector');
const authModal = document.querySelector('#auth-modal');
const walletModal = document.querySelector('#wallet-modal');
const walletSettingsButton = document.querySelector('#wallet-settings-button');
const billSettingsButton = document.querySelector('#bill-settings-button');
const logoutButton = document.querySelector('#logout-button');
let currentAccount = null;
let emailVerificationRequired = false;
let authDismissed = false;
let registrationToken = '';
const linkMatch = location.hash.match(/^#register=([a-f0-9]{64})$/);
if (linkMatch) { registrationToken = linkMatch[1]; history.replaceState(null, '', location.pathname + location.search); }
fetch('/api/auth/config').then(response => response.ok ? response.json() : {}).then(config => {
  emailVerificationRequired = Boolean(config.email_verification_required);
  window.AuthChallenge?.configure(config);
  window.AuthChallenge?.mode(document.querySelector('#auth-form').dataset.mode || 'login');
  document.querySelector('#auth-email-code-field').hidden = !emailVerificationRequired || document.querySelector('#auth-form').dataset.mode !== 'register';
  if (registrationToken) {
    fetch('/api/auth/registration-link', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({registration_token:registrationToken})})
      .then(readApiResponse).then(data => {
        document.querySelector('#auth-email').value = data.email;
        setAuthMode('register'); showAuth();
        document.querySelector('#auth-description').textContent = '验证链接已载入，设置密码后完成注册。';
      }).catch(error => { registrationToken=''; showAuth(); const message=document.querySelector('#auth-error');message.textContent=error.message;message.hidden=false; });
  }
}).catch(() => {});
let accountReadSequence = 0;
let publishedAccountId;
let resolveInitialAccount;
const initialAccountReady = new Promise(resolve => { resolveInitialAccount = resolve; });
window.AccountLifecycle = {
  async checkResponse(response) {
    const owner = response.headers.get('X-Account-ID');
    if (!owner) return;
    await initialAccountReady;
    if (owner !== currentAccount?.id) throw new Error('账号已切换，已忽略之前的响应');
  },
};
const accountSignalKey = 'universe.account.changed';
window.addEventListener('account-changed', () => {
  ++accountReadSequence;
  const next = currentAccount?.id || null;
  if (next === publishedAccountId) return;
  const previous = publishedAccountId;
  publishedAccountId = next;
  if (previous !== undefined) {
    document.querySelectorAll('#wallet-modal, #api-settings-modal, #admin-users-modal').forEach(node => { node.hidden = true; });
    document.querySelectorAll('#wallet-transactions, #admin-users-list, #admin-user-detail, #xhs-result, #tie-result, #hit-result').forEach(node => { node.textContent = ''; });
    document.querySelectorAll('#xhs-result, #tie-result, #hit-result').forEach(node => { node.hidden = true; });
    document.querySelectorAll('#api-settings-modal input').forEach(node => { node.value = ''; });
  }
  try { localStorage.setItem(accountSignalKey, globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`); } catch { /* Storage may be disabled. */ }
});
window.addEventListener('storage', event => {
  if (event.key === accountSignalKey) loadAccount();
});
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') loadAccount();
});
let currentWallet = { balance: 0, trial: 0, bonus: 0, paid: 0 };
const sharedKeys = {
  text: 'shared_text_api_key_v1',
  image: 'shared_image_api_key_v1',
  textBaseUrl: 'shared_text_base_url_v1',
  imageBaseUrl: 'shared_image_base_url_v1',
};

const esc = (value) => String(value ?? '无').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
const number = (value) => new Intl.NumberFormat('zh-CN').format(Number(value || 0));
const one = (value) => Number(value || 0).toFixed(1);
const safeUrl = (value) => {
  const raw = String(value || '').trim();
  if (/^https?:\/\//i.test(raw)) return raw;
  if (/^\/api\/creator-tools\/assets\/[a-zA-Z0-9_./-]+$/.test(raw)) return raw;
  if (/^\/\//.test(raw)) return `https:${raw}`;
  return '';
};
const cleanApiKey = (value) => String(value || '').replace(/[\s\u00a0\u200b-\u200d\ufeff]/g, '');
const getSharedTextKey = () => cleanApiKey(localStorage.getItem(sharedKeys.text) || '');
const getSharedImageKey = () => cleanApiKey(localStorage.getItem(sharedKeys.image) || '');
const getStored = (key, fallback = '') => String(localStorage.getItem(key) ?? fallback);
const getTextBaseUrl = () => getStored(sharedKeys.textBaseUrl, 'https://huoxingapi.com/v1').trim();
const getImageBaseUrl = () => getStored(sharedKeys.imageBaseUrl, 'https://img.rjm.us.ci').trim();
const sharedApiPayload = () => ({});

function syncAdminVisibility() {
  if (logoutButton) logoutButton.textContent = currentAccount ? '退出登录' : '登录 / 注册';
  const isAdmin = currentAccount?.role === 'admin' && currentAccount?.email?.toLowerCase() === 'gelen5@163.com';
  if (apiSettingsButton) apiSettingsButton.hidden = !isAdmin;
  if (adminUsersButton) adminUsersButton.hidden = !isAdmin;
  // 账单页含平台经营收入，只对站长本人（gelen5@163.com 且为管理员）开放入口。
  // 后端 /bill 另有独立拦截，这里只负责不给其他人看到这个按钮。
  if (billSettingsButton) billSettingsButton.hidden = !isAdmin;
  if (!isAdmin && apiSettingsModal) apiSettingsModal.hidden = true;
  if (!isAdmin && adminUsersModal) adminUsersModal.hidden = true;
  const impersonating = Boolean(currentAccount?.impersonation?.active);
  const banner = document.querySelector('#impersonation-banner');
  if (banner) banner.hidden = !impersonating;
  if (impersonating) document.querySelector('#impersonation-user-name').textContent = `${currentAccount.display_name}（${currentAccount.email}）`;
}

const formatDate = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '从未登录';

async function loadAdminUsers(query = '') {
  const overviewData = await readApiResponse(await fetch('/api/admin/overview'));
  const usersData = await readApiResponse(await fetch(`/api/admin/users?query=${encodeURIComponent(query)}`));
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
  try { await loadAdminUsers(); await loadAdminTasks(); } catch (error) { adminUsersModal.hidden = true; showToast(error.message, 'error'); }
}

async function switchToUser(userId) {
  if (!window.confirm('切换后将以该用户的积分和权限使用工作台。所有切换行为都会记录，是否继续？')) return;
  try {
    await prepareAccountChange();
    const data = await readApiResponse(await fetch('/api/admin/impersonate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: userId }) }));
    currentAccount = data.user;
    window.dispatchEvent(new Event('account-changed'));
    renderWallet(data.wallet);
    adminUsersModal.hidden = true;
    syncAdminVisibility();
    showToast(`已切换到 ${currentAccount.display_name} 的用户视角`);
  } catch (error) { showToast(error.message, 'error'); }
}

async function stopImpersonation() {
  try {
    await prepareAccountChange();
    const data = await readApiResponse(await fetch('/api/auth/stop-impersonation', { method: 'POST' }));
    currentAccount = data.user;
    window.dispatchEvent(new Event('account-changed'));
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
  toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
  toast.setAttribute('aria-live', type === 'error' ? 'assertive' : 'polite');
  toast.innerHTML = `<i data-lucide="${type === 'success' ? 'check-circle-2' : 'circle-alert'}"></i><span>${esc(message)}</span>`;
  document.body.appendChild(toast);
  window.lucide?.createIcons();
  requestAnimationFrame(() => toast.classList.add('visible'));
  setTimeout(() => { toast.classList.remove('visible'); setTimeout(() => toast.remove(), 220); }, 2600);
}

async function readApiResponse(response) {
  await window.AccountLifecycle.checkResponse(response);
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    if ([502, 503, 504].includes(response.status)) {
      throw new Error('AI 生成时间超过网关等待上限，任务可能仍在服务器继续执行。请先等待一分钟并刷新页面，避免重复提交。');
    }
    throw new Error(`服务器响应格式异常（HTTP ${response.status}，${contentType || '未知格式'}），请刷新页面后重试`);
  }
  const data = await response.json();
  window.PointsNotice?.fromResponse(response, data);
  const headerBalance = response.headers.get('X-Points-Balance');
  if (headerBalance !== null) setWalletBalance(Number(headerBalance));
  if (response.status === 401) showAuth();
  if (!response.ok) throw new Error(data.detail || data.message || `请求失败（HTTP ${response.status}）`);
  return data;
}

function setWalletBalance(balance) {
  if (balance === null || balance === undefined || String(balance).trim() === '' || !Number.isFinite(Number(balance))) return;
  currentWallet.balance = Number(balance);
  const top = document.querySelector('#wallet-balance');
  const modal = document.querySelector('#wallet-modal-balance');
  if (top) top.textContent = number(currentWallet.balance);
  if (modal) modal.textContent = number(currentWallet.balance);
}

function renderWallet(wallet = {}) {
  window.dispatchEvent(new Event('creator-account-changed'));
  currentWallet = { ...currentWallet, ...wallet };
  setWalletBalance(currentWallet.balance);
  document.querySelector('#wallet-trial').textContent = number(currentWallet.trial);
  document.querySelector('#wallet-bonus').textContent = number(currentWallet.bonus);
  document.querySelector('#wallet-paid').textContent = number(currentWallet.paid);
}

function showAuth(force = false) {
  if (currentAccount) return;
  if (force) authDismissed = false;
  if (authModal && authModal.hidden) {
    if (!authModal.dataset.initialModeSet) { setAuthMode('register'); authModal.dataset.initialModeSet='true'; }
    const close=document.querySelector('#auth-close');if(close)close.hidden=true;
    for(const child of appShell?.children||[])if(!child.contains(authModal)&&child!==authModal)child.inert=true;
    authModal.hidden = false;
    document.body.classList.add('auth-open');
    // Keep the keyboard closed on touch devices until a field is chosen.
    authModal.querySelector('[data-auth-mode].active')?.focus({ preventScroll: true });
  }
}

function hideAuth() {
  if (authModal) authModal.hidden = true;
  document.body.classList.remove('auth-open');
  for(const child of appShell?.children||[])child.inert=false;
}

function setAuthMode(mode) {
  const register = mode === 'register';
  window.AuthChallenge?.mode(mode);
  document.querySelectorAll('[data-auth-mode]').forEach(button => {
    button.classList.toggle('active', button.dataset.authMode === mode);
    button.setAttribute('aria-pressed', String(button.dataset.authMode === mode));
  });
  document.querySelector('#display-name-field').hidden = !register;
  document.querySelector('#invite-code-field').hidden = !register;
  document.querySelector('#auth-email-code-field').hidden = !register || !emailVerificationRequired || Boolean(registrationToken);
  document.querySelector('#auth-title').textContent = register ? '创建你的账号' : '欢迎回来';
  document.querySelector('#auth-description').textContent = register ? '从一个想法，开始你的创作。' : '登录，继续你的创作。';
  document.querySelector('#auth-submit').textContent = register ? '注册并进入工作台' : '登录';
  document.querySelector('#auth-password').autocomplete = register ? 'new-password' : 'current-password';
  document.querySelector('#auth-form').dataset.mode = mode;
  document.querySelector('#auth-error').hidden = true;
}

function dismissAuth() {
  if (!currentAccount) return;
  authDismissed = true;
  hideAuth();
  document.querySelector('#logout-button')?.focus({preventScroll:true});
}
document.querySelector('#auth-close')?.addEventListener('click', dismissAuth);
// A later deliberate action in the workbench may require signing in again.
// The close button's own bubbling event must not undo the dismissal.
document.addEventListener('click', event => {
  if (!event.target.closest('#auth-modal')) authDismissed = false;
});

document.querySelectorAll('[data-auth-mode]').forEach(button => button.addEventListener('click', () => setAuthMode(button.dataset.authMode)));

document.querySelector('#auth-send-code')?.addEventListener('click', async event => {
  const button = event.currentTarget;
  const error = document.querySelector('#auth-error');
  error.hidden = true;
  button.disabled = true;
  try {
    const challenge = await window.AuthChallenge?.getToken('register_email');
    const response = await fetch('/api/auth/email-code', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: document.querySelector('#auth-email').value.trim(), ...(challenge ? {turnstile_token: challenge} : {}) }),
    });
    await readApiResponse(response);
    let seconds = 60;
    button.textContent = `${seconds} 秒后重发`;
    const cooldown = setInterval(() => {
      seconds -= 1;
      button.textContent = seconds > 0 ? `${seconds} 秒后重发` : '重新发送';
      if (seconds <= 0) { clearInterval(cooldown); button.disabled = false; }
    }, 1000);
  } catch (exception) {
    error.textContent = exception.message;
    error.hidden = false;
    button.disabled = false;
  } finally { window.AuthChallenge?.reset(); }
});

document.querySelector('#auth-password-toggle')?.addEventListener('click', event => {
  const input = document.querySelector('#auth-password');
  const visible = input.type === 'password';
  input.type = visible ? 'text' : 'password';
  event.currentTarget.textContent = visible ? '隐藏' : '显示';
  event.currentTarget.setAttribute('aria-label', visible ? '隐藏密码' : '显示密码');
  event.currentTarget.setAttribute('aria-pressed', String(visible));
});
authModal?.addEventListener('keydown', event => {
  if (event.key === 'Escape') { event.preventDefault(); dismissAuth(); return; }
  if (event.key !== 'Tab') return;
  const controls = [...authModal.querySelectorAll('a[href], button:not(:disabled), input:not(:disabled)')].filter(el => el.getClientRects().length);
  const first = controls[0], last = controls.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
});

document.querySelector('#auth-form')?.addEventListener('submit', async event => {
  event.preventDefault();
  const mode = event.currentTarget.dataset.mode || 'login';
  const submit = document.querySelector('#auth-submit');
  const error = document.querySelector('#auth-error');
  error.hidden = true;
  const finish = beginButton(submit, mode === 'register' ? '正在注册…' : '正在登录…');
  try {
    const challenge = mode === 'register' ? await window.AuthChallenge?.getToken('register') : '';
    const response = await fetch(`/api/auth/${mode}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: document.querySelector('#auth-email').value.trim(),
        password: document.querySelector('#auth-password').value,
        display_name: document.querySelector('#auth-display-name').value.trim(),
        ...(mode === 'register' ? {ref: document.querySelector('#auth-invite-code').value.trim(), email_code: document.querySelector('#auth-email-code').value.trim(), ...(registrationToken ? {registration_token: registrationToken} : {})} : {}),
        ...(challenge ? {turnstile_token: challenge} : {}),
      }),
    });
    const data = await readApiResponse(response);
    currentAccount = data.user;
    window.dispatchEvent(new Event('account-changed'));
    syncAdminVisibility();
    renderWallet(data.wallet);
    hideAuth();
    document.querySelector('#wallet-user-line').textContent = `${currentAccount.display_name} · ${currentAccount.email}`;
    document.querySelector('.api-live-dot')?.classList.remove('offline');
    hideAuth();
    registrationToken = '';
    rememberInviteCode('');
    showToast(inviteToast(mode, data.referral));
    // 新注册的人是活动最强的传播源：当场把邀请码摆到他面前，而不是等他去翻设置。
    if (mode === 'register') guideToInvite();
  } catch (exception) {
    error.textContent = exception.message;
    error.hidden = false;
  } finally { finish(); window.AuthChallenge?.reset(); }
});

// ---- 拉新活动：邀请码 ----

const INVITE_CODE_KEY = 'universe-invite-code';

function normalizeInviteCode(value) {
  return String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 16);
}

function rememberInviteCode(code) {
  try {
    if (code) localStorage.setItem(INVITE_CODE_KEY, code);
    else localStorage.removeItem(INVITE_CODE_KEY);
  } catch { /* 隐私模式下 localStorage 会抛错，邀请码只是便利功能 */ }
}

function pendingInviteCode() {
  // URL 上的 ?ref= 优先，其次是上次点进来时记住的那一个。
  const fromUrl = new URLSearchParams(location.search).get('ref');
  if (fromUrl) { const code = normalizeInviteCode(fromUrl); rememberInviteCode(code); return code; }
  try { return normalizeInviteCode(localStorage.getItem(INVITE_CODE_KEY)); } catch { return ''; }
}

// 带着邀请链接进来的人，注册表单默认就是展开的。
(function seedInviteCode() {
  const code = pendingInviteCode();
  if (!code) return;
  const input = document.querySelector('#auth-invite-code');
  if (input) input.value = code;
  document.querySelector('#auth-modal')?.setAttribute('data-invited', '1');
})();

function inviteToast(mode, referral) {
  if (mode !== 'register' || !referral || referral.status !== 'bound') {
    return mode === 'register' ? '账号创建成功' : '登录成功';
  }
  return `账号创建成功，${referral.bonus} 积分的邀请奖励已到账`;
}

function inviteStatusLabel(status) {
  return { pending: '待完成任务', activated: '奖励发放中', rewarded: '已发奖励' }[status] || status;
}

function inviteLink(code) {
  return `${location.origin}/?ref=${encodeURIComponent(code)}`;
}

/* 注册完成后把邀请面板亮一下：不弹新窗口、不打断，只是让人看见自己也有码。 */
function guideToInvite() {
  openWallet()
    .then(() => {
      const panel = document.querySelector('#invite-panel');
      if (!panel || panel.hidden) return;
      panel.scrollIntoView({ block: 'nearest' });
      panel.classList.add('invite-panel-flash');
      setTimeout(() => panel.classList.remove('invite-panel-flash'), 1800);
    })
    .catch(() => { /* 引导失败不该影响注册成功 */ });
}

async function loadInvitePanel(panel) {
  const response = await fetch('/api/referrals', { cache: 'no-store' });
  const data = await readApiResponse(response);
  const info = data.referrals;
  panel.hidden = !info.enabled;
  if (!info.enabled) return;
  document.querySelector('#invite-code').textContent = info.code;
  document.querySelector('#invite-signup-reward').textContent = info.rewards.signup;
  const parts = [
    `已邀请 ${info.counts.total} 人`,
    `${info.counts.rewarded} 人已完成首个任务`,
    `累计获得 ${number(info.earned_points)} 积分`,
  ];
  if (info.caps.remaining_today <= 0) {
    parts.push(`今日名额已用完，明天再来`);
  } else {
    parts.push(`今天还能邀请 ${info.caps.remaining_today} 人`);
  }
  document.querySelector('#invite-stats').textContent = parts.join(' · ');
  const list = document.querySelector('#invite-list');
  list.innerHTML = info.invitees.length
    ? info.invitees.map(item => `<article><div><strong>${esc(item.display_name)}</strong><small>${esc(item.email)} · ${new Date(item.created_at).toLocaleDateString('zh-CN')}</small></div><span class="invite-status ${item.status}">${inviteStatusLabel(item.status)}</span></article>`).join('')
    : '<p>还没有人通过你的邀请码注册。把链接发出去试试。</p>';
  document.querySelector('#invite-copy').dataset.code = info.code;
}

document.querySelector('#invite-copy')?.addEventListener('click', async event => {
  const code = event.currentTarget.dataset.code || document.querySelector('#invite-code').textContent;
  if (!code || code === '—') return;
  const link = inviteLink(code);
  try {
    await navigator.clipboard.writeText(link);
    showToast('邀请链接已复制');
  } catch {
    // 非 HTTPS 或旧浏览器没有 clipboard，退回到能选中的输入框。
    window.prompt('复制这条邀请链接', link);
  }
});

let walletTransactions = [];
let walletFilter = 'all';

function transactionKind(item) {
  const kind = String(item.kind || '').toLowerCase();
  if (kind === 'recharge') return 'recharge';
  if (kind === 'refund') return 'refund';
  if (kind === 'consume') return 'consume';
  return item.amount > 0 ? 'recharge' : 'consume';
}

function alipayOrderNo(item) {
  const ref = String(item.request_id || '');
  const match = ref.match(/^alipay(?:-refund)?:([^:]+)/);
  return match ? match[1] : '';
}

function paintTransactions() {
  const root = document.querySelector('#wallet-transactions');
  if (!root) return;
  const list = walletFilter === 'all'
    ? walletTransactions
    : walletTransactions.filter(item => transactionKind(item) === walletFilter);
  if (!list.length) {
    root.innerHTML = `<p>${walletTransactions.length ? '该分类暂无记录' : '暂无积分记录'}</p>`;
    return;
  }
  root.innerHTML = list.map(item => {
    const orderNo = alipayOrderNo(item);
    const orderLine = orderNo ? `<span class="tx-order">订单 ${esc(orderNo)}</span>` : '';
    return `<article><span class="transaction-icon ${item.amount > 0 ? 'in' : 'out'}"><i data-lucide="${item.amount > 0 ? 'plus' : 'sparkles'}"></i></span><div><strong>${esc(item.feature || item.note || (item.amount > 0 ? '积分充值' : '功能消费'))}</strong><small>${esc(item.note || item.source)} · ${new Date(item.created_at).toLocaleString('zh-CN')}</small>${orderLine}</div><b class="${item.amount > 0 ? 'in' : 'out'}">${item.amount > 0 ? '+' : ''}${number(item.amount)}</b></article>`;
  }).join('');
  window.lucide?.createIcons();
}

function renderTransactions(items = []) {
  walletTransactions = Array.isArray(items) ? items : [];
  paintTransactions();
}

document.querySelector('#wallet-filters')?.addEventListener('click', event => {
  const button = event.target.closest('button[data-filter]');
  if (!button) return;
  walletFilter = button.dataset.filter;
  document.querySelectorAll('#wallet-filters button').forEach(node => node.classList.toggle('active', node === button));
  paintTransactions();
});

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
    // 邀请面板失败不能把钱包一起弄挂：钱包先开，面板再补。
    // 这里 await 是为了让 guideToInvite() 拿到渲染完成的面板。
    const invitePanel = document.querySelector('#invite-panel');
    await loadInvitePanel(invitePanel).catch(() => { invitePanel.hidden = true; });
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

walletSettingsButton?.addEventListener('click', () => { window.location.href = '/wallet'; });
billSettingsButton?.addEventListener('click', () => { window.location.href = '/bill'; });
document.querySelector('#wallet-chip')?.addEventListener('click', openWallet);
document.querySelector('#wallet-close')?.addEventListener('click', () => { walletModal.hidden = true; });
document.querySelector('#wallet-refresh')?.addEventListener('click', () => refreshWallet());
walletModal?.addEventListener('click', event => { if (event.target === walletModal) walletModal.hidden = true; });
async function prepareAccountChange() {
  const pending = [];
  window.dispatchEvent(new CustomEvent('before-account-change', { detail: { pending } }));
  await Promise.all(pending);
}

logoutButton?.addEventListener('click', async () => {
  if (!currentAccount) { toggleSettingsMenu(false); showAuth(true); return; }
  try {
    await prepareAccountChange();
    const response = await fetch('/api/auth/logout', { method: 'POST' });
    // A previous server release can answer 401 when this session has already
    // expired. That is an unauthenticated state, not a failed logout.
    if (!response.ok && response.status !== 401) throw new Error('退出未确认，请稍后重试');
  } catch (error) { showToast(error.message, 'error'); return; }
  currentAccount = null;
  window.dispatchEvent(new Event('account-changed'));
  syncAdminVisibility();
  renderWallet({ balance: 0, trial: 0, bonus: 0, paid: 0 });
  walletModal.hidden = true;
  showAuth(true);
});

async function loadAccount() {
  const sequence = ++accountReadSequence;
  try {
    const response = await fetch('/api/auth/me', { cache: 'no-store' });
    if (sequence !== accountReadSequence) return;
    if (!response.ok) {
      if (response.status === 401) {
        currentAccount = null;
        window.dispatchEvent(new Event('account-changed'));
        syncAdminVisibility();
        renderWallet({ balance: 0, trial: 0, bonus: 0, paid: 0 });
        showAuth();
      } else if (!currentAccount) {
        showAuth();
        const error = document.querySelector('#auth-error');
        error.textContent = '暂时无法确认登录状态，请稍后重试登录。';
        error.hidden = false;
      }
      return;
    }
    const data = await readApiResponse(response);
    if (sequence !== accountReadSequence) return;
    currentAccount = data.user;
    window.dispatchEvent(new Event('account-changed'));
    syncAdminVisibility();
    renderWallet(data.wallet);
    document.querySelector('#wallet-user-line').textContent = `${currentAccount.display_name} · ${currentAccount.email}`;
    document.querySelector('.api-live-dot')?.classList.remove('offline');
    restoreDurableWorkflow();
  } catch { if (!currentAccount) showAuth(); }
  finally { resolveInitialAccount(); }
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
    sharedTextModelInput.value = settings.text_model || '';
    sharedImageModelInput.value = settings.image_model || '';
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

settingsButton?.addEventListener('click', async (event) => {
  event.stopPropagation();
  if (!apiSettingsButton?.hidden) {
    await openApiSettings();
    return;
  }
  openWallet();
});
apiSettingsButton?.addEventListener('click', openApiSettings);
adminUsersButton?.addEventListener('click', () => { window.location.href = '/admin/users'; });
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
  if (!event.target.closest?.('.menu-wrap')) toggleSettingsMenu(false);
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

function renderReport(report, activate = true) {
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
  if (activate) setActiveView('report');
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
    showToast(error.message, 'error');
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
let durableWorkflow = null;
let workflowEventSource = null;
let workbenchSession = null;
let workbenchVersionIndex = -1;

const stepGuidance = {
  1: { label: '选择选题', title: '从下面的方向里，选一个你愿意写下去的。', detail: '选择后才会生成文章框架，不会直接生成整篇文章。', action: '选择方向后生成框架', next: '生成文章框架' },
  2: { label: '确认框架', title: '先看文章怎么展开，再决定是否写正文。', detail: '确认后会生成一篇可直接编辑的完整初稿。', action: '确认框架，生成初稿', next: '生成完整初稿' },
  3: { label: '编辑初稿', title: '这是你的文章初稿，可以直接改成自己的表达。', detail: '确认后才进入反 AI 审校；请先补充个人经历、事实或具体判断。', action: '确认正文，开始审校', next: '反 AI 审校' },
  4: { label: '确认文字', title: '文字复核完成，请检查语气和事实边界。', detail: '下一步先展示配图方案，不会直接生成图片。', action: '确认文字，策划配图', next: '配图方案' },
  5: { label: '确认配图方案', title: '检查每张图的用途、对应段落和图注。', detail: '确认后逐张生成并保存，再按 Skill 组件库排版。', action: '确认方案，生成图片并排版', next: '生图与排版' },
  6: { label: '生成预览', title: '排版已完成，下一步查看公众号实际粘贴效果。', detail: '预览页支持一键复制富文本，也可以下载 HTML 存档。', action: '打开预览并复制', next: '公众号富文本预览' },
  7: { label: '交付内容', title: '内容已经可以交付到公众号后台。', detail: '复制或下载 HTML 后粘贴到公众号；确认无误再写入草稿箱。', action: '写入公众号草稿箱', next: '写入草稿箱' },
  8: { label: '发布完成', title: '草稿写入流程已完成。', detail: '你仍可返回正文修改，并重新生成预览。', action: '完成', next: '—' },
};

function renderScoreReport(session) {
  const wrap = document.querySelector('#score-report');
  if (!wrap) return;
  const review = session?.review;
  if (session?.review_run?.status === 'blocked') {
    const run = session.review_run;
    const last = run.rounds?.[run.rounds.length - 1];
    wrap.hidden = false;
    wrap.innerHTML = `<section class="skill-review-result" role="status"><h3>去 AI 复核未通过</h3><p>已保留上一次正文，未进入配图。</p><p>${esc(run.error || '仍有问题需要处理')}</p><details><summary>查看本轮实际问题与审计</summary><pre>${esc(JSON.stringify(last || {}, null, 2))}</pre></details></section>`;
    return;
  }
  if (!review) { wrap.hidden = true; wrap.innerHTML = ''; return; }
  const audit = review.audit || {};
  const available = audit.status === 'success';
  const printable = value => typeof value === 'string' ? value : JSON.stringify(value);
  const warnings = Array.isArray(audit.warnings) ? audit.warnings : [];
  const missing = Object.entries(audit.missing_protected_spans || {}).filter(([, value]) =>
    Array.isArray(value) ? value.length : value && (typeof value !== 'object' || Object.keys(value).length));
  const numberOrMissing = value => value == null ? '未返回' : esc(value);
  const warningList = warnings.length ? `<ul>${warnings.map(item => `<li>${esc(printable(item))}</li>`).join('')}</ul>` : '<p>本次审计未返回可读性警告。</p>';
  const missingList = missing.length ? `<ul>${missing.map(([key,value]) => `<li><strong>${esc(key)}</strong>：${esc(printable(value))}</li>`).join('')}</ul>` : '<p>本次审计未报告保护片段缺失。</p>';
  wrap.hidden = false;
  wrap.innerHTML = `<section class="skill-review-result">
    <header><h3>去 AI 改写结果</h3><span>${available ? '审计已返回' : '审计不可用'}</span></header>
    <p>上方正文为本次返回的改写稿，可继续编辑并核对事实。</p>
    <p class="review-source">来源：${esc(review.source || '未返回')} · ${esc(review.action || '未返回处理说明')}</p>
    ${available ? `<dl><div><dt>改写前信号数</dt><dd>${numberOrMissing(audit.original_signal_total)}</dd></div><div><dt>改写后信号数</dt><dd>${numberOrMissing(audit.revision_signal_total)}</dd></div><div><dt>完整句比例</dt><dd>${audit.complete_sentence_ratio == null ? '未返回' : esc((Number(audit.complete_sentence_ratio) * 100).toFixed(1)) + '%'}</dd></div></dl>
      <h4>保护片段核对</h4>${missingList}<h4>可读性审计</h4>${warningList}
      <p class="review-source">信号数量用于对照改稿，不代表 AI 生成概率或发布结论。</p>` : '<p>未取得有效审计结果，不能判断保护片段和可读性是否通过。</p>'}
    <details><summary>查看 Skill 返回的审计数据</summary><pre>${esc(JSON.stringify(audit,null,2))}</pre></details>
  </section>`;
}

function renderDecisionPanel(session) {
  if (!session) {
    decisionPanel.innerHTML = `<div class="chat-welcome"><span class="chat-welcome-mark"><i data-lucide="sparkles"></i></span><h2>今天想写什么？</h2><p>用一句话告诉我主题。创作助手会先查询近期相关热点，再按最新版公众号 Skill 完成后续工作。</p><div class="starter-prompts"><button type="button" data-starter-prompt="查询最近一周中老年情感热点，给我 10 个适合公众号的选题">查询近期热点并给选题</button><button type="button" data-starter-prompt="写一篇关于婆媳矛盾的公众号文章，面向 45 岁以上女性，表达要真实克制">从一个主题开始写</button><button type="button" data-starter-prompt="我有一段素材，先帮我梳理适合公众号传播的写作方向">把已有素材变成文章</button></div></div>`;
    decisionPanel.querySelectorAll('[data-starter-prompt]').forEach(button => button.addEventListener('click', () => {
      topicInput.value = button.dataset.starterPrompt || '';
      topicInput.focus();
    }));
    const flowLabel = document.querySelector('#flow-step-label');
    const flowHint = document.querySelector('#flow-step-hint');
    if (flowLabel) flowLabel.textContent = '等待你的想法';
    if (flowHint) flowHint.textContent = '在对话区输入需求，开始选题';
    runNextButton.innerHTML = '等待输入需求';
    runNextButton.hidden = true;
    runNextButton.disabled = true;
    previewButton.hidden = true;
    document.querySelector('#publish-draft').hidden = true;
    window.lucide?.createIcons();
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
  const seed = !workbenchSession ? [] : history;
  thread.innerHTML = seed.length ? seed.map(item => `<article class="chat-message ${item.role === 'user' ? 'from-user' : 'from-ai'}"><span>${item.role === 'user' ? '你' : 'AI 共创助手'}</span><p>${esc(item.content)}</p></article>`).join('') : `<article class="chat-message from-ai"><span>AI 共创助手</span><p>我已准备好。你可以选一个方向，也可以说说哪里不满意。</p></article>`;
  thread.scrollTop = thread.scrollHeight;
}

function appendWorkbenchPending(message, label = '正在调用公众号创作 Skill…') {
  const thread = document.querySelector('#workbench-chat-thread');
  if (!thread) return;
  thread.insertAdjacentHTML('beforeend', `<article class="chat-message from-user"><span>你</span><p>${esc(message)}</p></article><article class="chat-message from-ai is-pending" data-workbench-pending><span>公众号创作助手</span><p><i></i>${esc(label)}</p></article>`);
  thread.scrollTop = thread.scrollHeight;
}

function syncWorkbenchModePicker() {
  const locked = !!workbenchSession || workbench?.classList.contains('is-running');
  if (workbench) workbench.dataset.sessionActive = workbenchSession ? 'true' : 'false';
  modeButtons.forEach(button => {
    button.classList.toggle('active', button.dataset.mode === workbenchMode);
    button.disabled = locked;
  });
}

function setWorkbenchBusy(active) {
  workbench?.classList.toggle('is-running', active);
  if (topicInput) topicInput.disabled = active;
  const newChat = document.querySelector('#new-workbench-chat');
  if (newChat) newChat.disabled = active;
  syncWorkbenchModePicker();
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
  // Server invalidates images when the article changes. Never revive stale art.
  const previousStep = workbenchSession?.current_step || 0;
  workbenchSession = session;
  workbenchMode = session.mode === 'single' ? 'step' : (session.mode || workbenchMode);
  syncWorkbenchModePicker();
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
  renderScoreReport(session);
  document.querySelector('#score-label').textContent = session.review ? '去 AI 改写稿 · 实际审计记录见下方' : '当前正文 · 第 4 步执行去 AI 改写';
  document.querySelector('#result-meta').textContent = session.framework
    ? `${session.framework.name} 框架 · ${session.persona || '默认人格'} · 平台服务已连接`
    : '正在生成写作方向';
  const htmlDownload = document.querySelector('#download-workbench-html');
  if (htmlDownload) {
    htmlDownload.hidden = !session.html_download_url;
    htmlDownload.href = session.html_download_url || '#';
  }
  const suggestions = session.suggestions || [];
  topicList.innerHTML = session.current_step === 1 && suggestions.length ? `<div class="chat-choice-head"><strong>10 个可写方向</strong><span>热度与涨粉分均为 Skill 基于检索信号的估计，不是平台真实统计</span></div>${suggestions.slice(0, 10).map(item => `<article class="chat-choice"><span>${String(item.id).padStart(2, '0')}</span><div><strong>${esc(item.title)}</strong><p>${esc(item.reason)}</p><small>${esc(item.type)} · 竞争度 ${esc(item.competition || '中')}</small><div class="topic-metrics"><span>热度 <b>${Number(item.heat || 0)}/10</b></span><span>涨粉潜力 <b>${Number(item.fan_score || 0)}/100</b></span></div></div><footer><button class="adopt-topic" data-topic-id="${item.id}" type="button">采用这个方向</button></footer></article>`).join('')}` : '';
  topicList.querySelectorAll('.adopt-topic').forEach(item => item.addEventListener('click', async () => { await advance(Number(item.dataset.topicId), 2); renderChatThread(workbenchSession); }));
  topicList.querySelectorAll('.regenerate-topic').forEach(item => item.addEventListener('click', () => sendWorkbenchChat('这个方向不错，但请换一个更有冲突和具体场景的写法。', 'regenerate_topics')));
  renderOutline(session);
  let evidence = document.querySelector('#workbench-execution-evidence');
  if (!evidence) { evidence = document.createElement('details'); evidence.id = 'workbench-execution-evidence'; generatedImages.before(evidence); }
  const research = session.framework?.research || session.topic_research;
  const executions = session.skill_execution || [];
  const latestExecution = new Map();
  executions.forEach(item => latestExecution.set(Number(item.step), item));
  const executionRows = [...latestExecution.values()].sort((a,b) => Number(a.step) - Number(b.step)).map(item => {
    const status = item.status === 'passed' ? '已完成' : item.status === 'skipped' ? '按选择跳过' : item.status === 'blocked' ? '已拦截' : '执行中';
    const scripts = (item.scripts || []).join('、');
    return `<li class="skill-evidence-${esc(item.status || 'running')}"><b>第${esc(item.step)}步 ${esc(item.name || '')}</b><span>${status}</span><small>${esc(item.operation || '')}${scripts ? ` · ${esc(scripts)}` : ''}</small></li>`;
  }).join('');
  const passedSteps = [...latestExecution.values()].filter(item => item.status === 'passed').length;
  evidence.innerHTML = `<summary><span>查看本次 Skill 执行记录</span><small>${passedSteps} 项已验证</small></summary><p class="skill-gate-note">${esc(session.skill_gate?.message || '每个节点必须完成 Skill 执行后才能继续')}</p><ol class="skill-evidence-list">${executionRows || '<li>尚未开始</li>'}</ol><p>${esc(research?.limitations || '尚未检索')}</p>${(research?.sources || []).map(source=>`<p><a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title)}</a> · ${esc(source.verification)}</p>`).join('')}<p>${esc(session.history_check?.note || '')}</p><pre>${esc(JSON.stringify({layout:session.layout_plan, checks:session.layout_check, compliance:session.compliance_check},null,2))}</pre>`;
  window.lucide?.createIcons();
  const images = session.images || [];
  generatedImages.hidden = !images.length;
  const remoteImages = images.filter(image => image.delivery === 'remote').length;
  generatedImages.innerHTML = images.length ? `<div class="image-section-head"><div><span class="micro-label">API 生成配图</span><h3>封面与正文配图</h3></div><span>${images.length} 张 · ${remoteImages ? `${remoteImages} 张由供应商 CDN 提供` : '已自动压缩至微信限制内'}</span></div><div class="image-grid">${images.map(image => `<a href="${esc(image.url)}" target="_blank" rel="noopener"><img src="${esc(image.url)}" alt="${image.kind === 'cover' ? '文章封面' : '正文配图'}" /><span><strong>${image.kind === 'cover' ? '文章封面' : '正文配图'}</strong><small>${image.delivery === 'remote' ? '外链预览' : `${Math.round(Number(image.bytes || 0) / 1024)} KB`}</small></span></a>`).join('')}</div>` : '';
  if (session.image_plan) {
    generatedImages.hidden = false;
    generatedImages.insertAdjacentHTML('afterbegin', `<details open><summary>配图方案 · ${esc(session.image_plan.status)}</summary><p>${esc(session.image_plan.reason || '')}</p>${(session.image_plan.images || []).map((item,index)=>`<p><strong>${index+1}. ${item.kind === 'cover' ? '封面' : esc(item.section || '正文图')}</strong><br>${esc(item.claim || '')}<br>图注：${esc(item.caption || '')}</p>`).join('')}</details>`);
  }
  if (previousStep !== (session.current_step || 1)) {
    requestAnimationFrame(() => decisionPanel?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  }
}

function setWorkbenchProgress(target, active = true, message = '') {
  if (!workbenchProgress) return;
  setWorkbenchBusy(active);
  workbenchProgress.hidden = !active;
  workbenchProgress.style.display = active ? '' : 'none';
  if (!active) return;
  const labels = { 2: '正在检索素材并生成框架', 3: '正在生成完整初稿', 4: '正在进行去 AI 修改与复核', 5: '正在策划配图方案', 6: '正在生成图片并排版', 7: '正在生成手机端预览' };
  const details = { 2: '先确认文章怎么展开', 3: '正在组织正文', 4: '检查表达、事实边界和可读性', 5: '图片生成可能需要数分钟，请勿重复点击', 6: '把正文和图片整理成可复制内容', 7: '生成最终可查看、可下载的文件' };
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

async function waitForWorkbenchJob(jobId, signal) {
  for (;;) {
    const data = await readApiResponse(await fetch(`/api/workbench/jobs/${encodeURIComponent(jobId)}`, { signal }));
    const job = data.job || {};
    document.querySelector('#workbench-status').textContent = job.status === 'queued' ? '任务排队中' : 'Skill 执行中';
    if (job.status === 'completed' && data.session) return data.session;
    if (job.status === 'failed') throw new Error(job.error || '创作任务失败，积分已自动退还');
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
}

async function fetchDurableWorkflow(workflowId) {
  const response = await fetch(`/api/workflows/${encodeURIComponent(workflowId)}`);
  return (await readApiResponse(response)).workflow;
}

async function fetchLegacyWorkbenchSession(sessionId) {
  const response = await fetch(`/api/workbench/sessions/${encodeURIComponent(sessionId)}`);
  return (await readApiResponse(response)).session;
}

function waitForDurableWorkflow(workflow, signal) {
  durableWorkflow = workflow;
  localStorage.setItem('universe.activeWorkflowId', workflow.id);
  return new Promise((resolve, reject) => {
    let settled = false;
    let pollTimer = null;
    const finish = async () => {
      if (settled) return;
      try {
        durableWorkflow = await fetchDurableWorkflow(workflow.id);
        const status = durableWorkflow.status;
        document.querySelector('#workbench-status').textContent = status === 'queued' ? '任务排队中' : status === 'awaiting_input' ? '等待确认' : 'Skill 执行中';
        if (status === 'failed') { localStorage.removeItem('universe.activeWorkflowId'); throw new Error(durableWorkflow.error || '创作任务失败，积分已自动退还'); }
        if (status === 'cancelled') { localStorage.removeItem('universe.activeWorkflowId'); throw new DOMException('任务已取消', 'AbortError'); }
        if (!['awaiting_input', 'completed'].includes(status)) return;
        settled = true;
        clearInterval(pollTimer);
        workflowEventSource?.close();
        workflowEventSource = null;
        resolve(await fetchLegacyWorkbenchSession(workflow.id));
      } catch (error) {
        if (!settled && error.name !== 'AbortError' && !String(error.message || '').includes('Failed to fetch')) {
          settled = true;
          clearInterval(pollTimer);
          workflowEventSource?.close();
          workflowEventSource = null;
          reject(error);
        }
      }
    };
    workflowEventSource?.close();
    workflowEventSource = new EventSource(`/api/workflows/${encodeURIComponent(workflow.id)}/events`);
    ['workflow.created', 'node.queued', 'node.started', 'node.completed', 'workflow.awaiting_input', 'workflow.completed', 'workflow.failed', 'workflow.cancelled'].forEach(type => workflowEventSource.addEventListener(type, finish));
    workflowEventSource.onerror = () => { /* Polling below covers proxy/network gaps. */ };
    pollTimer = setInterval(finish, 1500);
    signal?.addEventListener('abort', () => {
      if (settled) return;
      settled = true;
      clearInterval(pollTimer);
      workflowEventSource?.close();
      workflowEventSource = null;
      reject(new DOMException('等待已取消', 'AbortError'));
    }, { once: true });
    finish();
  });
}

async function restoreDurableWorkflow() {
  const workflowId = localStorage.getItem('universe.activeWorkflowId');
  if (!workflowId || workbenchSession) return;
  try {
    durableWorkflow = await fetchDurableWorkflow(workflowId);
    if (['failed', 'cancelled'].includes(durableWorkflow.status)) {
      localStorage.removeItem('universe.activeWorkflowId');
      return;
    }
    if (['awaiting_input', 'completed'].includes(durableWorkflow.status)) {
      workbenchSession = await fetchLegacyWorkbenchSession(workflowId);
      renderWorkbenchSession(workbenchSession);
      return;
    }
    workbenchController = new AbortController();
    setWorkbenchProgress(1, true, '正在恢复未完成任务');
    workbenchSession = await waitForDurableWorkflow(durableWorkflow, workbenchController.signal);
    renderWorkbenchSession(workbenchSession);
  } catch (error) {
    if (error.name !== 'AbortError') showToast(`恢复任务失败：${error.message}`, 'error');
  } finally {
    setWorkbenchProgress(workbenchSession?.current_step || 1, false);
    workbenchController = null;
  }
}

async function advance(selection = null, nextStep = null) {
  if (!workbenchSession) return;
  const target = nextStep || Math.min(8, (workbenchSession.current_step || 1) + 1);
  workbenchController = new AbortController();
  setWorkbenchProgress(target);
  try {
    if (durableWorkflow && durableWorkflow.status === 'awaiting_input') {
      const decision = durableWorkflow.current_node === 'topic' ? { selection: selection || 1 } :
        durableWorkflow.current_node === 'visual' ? { image_policy: workbenchSession.image_policy || 'auto' } : {};
      const response = await fetch(`/api/workflows/${encodeURIComponent(durableWorkflow.id)}/decisions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: workbenchController.signal,
        body: JSON.stringify({ node: durableWorkflow.current_node, expected_version: durableWorkflow.version, decision }),
      });
      const accepted = await readApiResponse(response);
      durableWorkflow = accepted.workflow;
      workbenchSession = await waitForDurableWorkflow(durableWorkflow, workbenchController.signal);
    } else {
      workbenchSession = await callWorkbench('/api/workbench/steps', { session_id: workbenchSession.id, step: target, selection, article: articleEditor.value }, workbenchController.signal);
    }
    renderWorkbenchSession(workbenchSession);
  } catch (error) {
    try {
      const response = await fetch(`/api/workbench/sessions/${encodeURIComponent(workbenchSession.id)}`);
      if (response.ok) renderWorkbenchSession((await response.json()).session);
    } catch { /* Keep the original execution error if readback also fails. */ }
    throw error;
  } finally {
    setWorkbenchProgress(target, false);
    workbenchController = null;
  }
}

modeButtons.forEach(button => button.addEventListener('click', () => {
  if (workbenchSession || button.disabled) return;
  workbenchMode = button.dataset.mode;
  syncWorkbenchModePicker();
}));

function resolveWorkbenchChatAction(message) {
  return 'auto';
}

startWorkbench?.addEventListener('click', async () => {
  const message = topicInput.value.trim();
  if (!message) { topicInput.focus(); return; }
  if (workbenchSession) { await sendWorkbenchChat(message, resolveWorkbenchChatAction(message)); return; }
  workbenchController = new AbortController();
  startWorkbench.disabled = true;
  appendWorkbenchPending(message, '正在检索近期信号并生成选题…');
  setWorkbenchProgress(1, true, '正在检索近期信号并生成选题');
  const originalLabel = startWorkbench.innerHTML;
  startWorkbench.innerHTML = '正在提交…';
  try {
    if (workbenchMode !== 'step') {
      const response = await fetch('/api/workflows', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ topic: message, mode: workbenchMode, persona: document.querySelector('#workbench-persona').value, theme: document.querySelector('#workbench-theme').value, idempotency_key: newIdempotencyKey() }), signal: workbenchController.signal });
      const accepted = await readApiResponse(response);
      durableWorkflow = accepted.workflow;
      workbenchTaskId = durableWorkflow.id;
      startWorkbench.innerHTML = '正在生成选题…';
      const session = await waitForDurableWorkflow(durableWorkflow, workbenchController.signal);
      renderWorkbenchSession(session);
      topicInput.value = '';
      return;
    }
    const response = await fetch('/api/workbench/sessions', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...sharedApiPayload(), topic: message, mode: workbenchMode, persona: document.querySelector('#workbench-persona').value, theme: document.querySelector('#workbench-theme').value, idempotency_key: newIdempotencyKey() }), signal: workbenchController.signal });
    const accepted = await readApiResponse(response);
    workbenchTaskId = accepted.job.id;
    startWorkbench.innerHTML = '正在生成选题…';
    const session = await waitForWorkbenchJob(accepted.job.id, workbenchController.signal);
    renderWorkbenchSession(session);
    topicInput.value = '';
  } catch (error) { document.querySelector('[data-workbench-pending]')?.remove(); if (error.name !== 'AbortError') showToast(error.message, 'error'); } finally { workbenchTaskId = null; workbenchController = null; setWorkbenchProgress(1, false); startWorkbench.disabled = false; startWorkbench.innerHTML = originalLabel; }
});
async function sendWorkbenchChat(message, action = 'rewrite_article', selectionText = '') {
  if (!workbenchSession) return;
  const send = startWorkbench;
  send.disabled = true;
  appendWorkbenchPending(message);
  setWorkbenchProgress(workbenchSession.current_step || 1, true, '正在理解并执行你的要求');
  const original = send.innerHTML;
  send.textContent = '…';
  try {
    const session = await callWorkbench('/api/workbench/chat', { session_id: workbenchSession.id, message, action, selection_text: selectionText });
    renderWorkbenchSession(session);
    topicInput.value = '';
  } catch (error) { document.querySelector('[data-workbench-pending]')?.remove(); showToast(error.message, 'error'); } finally { setWorkbenchProgress(workbenchSession?.current_step || 1, false); send.disabled = false; send.innerHTML = original || '↑'; }
}

topicInput?.addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  if (!startWorkbench.disabled) startWorkbench.click();
});

runNextButton?.addEventListener('click', async () => {
  if (!workbenchSession) return;
  const current = workbenchSession.current_step || 1;
  if (current < 2 || current >= 7) return;
  runNextButton.disabled = true;
  try { await advance(null, current + 1); } catch (error) { if (error.name !== 'AbortError') showToast(error.message, 'error'); } finally { runNextButton.disabled = false; }
});
cancelWorkbenchButton?.addEventListener('click', async () => {
  if (!workbenchController) return;
  cancelWorkbenchButton.disabled = true;
  try {
    if (durableWorkflow && !['completed', 'failed', 'cancelled'].includes(durableWorkflow.status)) {
      await fetch(`/api/workflows/${encodeURIComponent(durableWorkflow.id)}/cancel`, { method: 'POST' });
    } else if (workbenchTaskId) {
      await fetch(`/api/tasks/${encodeURIComponent(workbenchTaskId)}/cancel`, { method: 'POST' });
    } else if (workbenchSession) {
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
document.querySelector('#workbench-regenerate-topics')?.addEventListener('click', () => { if (workbenchSession) sendWorkbenchChat('请重新给我 10 个方向，角度更具体，不要泛泛而谈，并返回每条的热度和涨粉潜力分。', 'regenerate_topics'); else topicInput.focus(); });
document.querySelector('#new-workbench-chat')?.addEventListener('click', () => { workflowEventSource?.close(); durableWorkflow = null; localStorage.removeItem('universe.activeWorkflowId'); workbenchSession = null; workbenchVersionIndex = -1; setWorkbenchBusy(false); topicInput.value = ''; articleEditor.value = ''; document.querySelector('#result-title').textContent = '还没有开始写'; document.querySelector('#article-save-state').textContent = '输入一个主题后，我会先和你确认写作方向'; document.querySelector('#article-version-label').textContent = '当前草稿 · 尚未生成'; document.querySelector('#article-change-label').textContent = '等待你的写作意图'; document.querySelector('#workbench-status').textContent = '等待你的想法'; topicList.innerHTML = ''; renderChatThread(null); renderOutline({}); });
document.querySelectorAll('[data-rewrite-selection]').forEach(button => button.addEventListener('click', () => { if (!workbenchSession) return; const selection = articleEditor.value.slice(articleEditor.selectionStart, articleEditor.selectionEnd); if (!selection) { showToast('先在当前文章中选中一段，再告诉我如何改写。', 'error'); return; } sendWorkbenchChat(button.dataset.rewriteSelection, 'rewrite_article', selection); }));
document.querySelector('#version-back')?.addEventListener('click', () => { const versions = workbenchSession?.versions || []; if (!versions.length) return; workbenchVersionIndex = workbenchVersionIndex < 0 ? versions.length - 1 : Math.max(0, workbenchVersionIndex - 1); articleEditor.value = versions[workbenchVersionIndex].article || ''; document.querySelector('#article-version-label').textContent = `${versions[workbenchVersionIndex].label} · 历史版本预览`; });
document.querySelector('#version-forward')?.addEventListener('click', () => { const versions = workbenchSession?.versions || []; if (workbenchVersionIndex < 0) return; workbenchVersionIndex += 1; if (workbenchVersionIndex >= versions.length) { workbenchVersionIndex = -1; articleEditor.value = workbenchSession.article || ''; document.querySelector('#article-version-label').textContent = `当前版本 · V${versions.length + 1}`; return; } articleEditor.value = versions[workbenchVersionIndex].article || ''; document.querySelector('#article-version-label').textContent = `${versions[workbenchVersionIndex].label} · 历史版本预览`; });
document.querySelector('#open-preview')?.addEventListener('click', async () => {
  if (!workbenchSession) return;
  try { const session = await callWorkbench('/api/workbench/preview', { session_id: workbenchSession.id, article: articleEditor.value }); renderWorkbenchSession(session); window.open(session.preview_url, '_blank', 'noopener'); } catch (error) { showToast(error.message, 'error'); }
});
document.querySelector('#publish-draft')?.addEventListener('click', async () => {
  if (!confirm('将当前预览写入公众号草稿箱？这不会发布文章。')) return;
  if (!workbenchSession) return;
  try { const session = await callWorkbench('/api/workbench/publish', { session_id: workbenchSession.id, draft: true }); renderWorkbenchSession(session); showToast(session.publish?.message || '已完成'); } catch (error) { showToast(error.message, 'error'); }
});
editCurrentButton?.addEventListener('click', () => { articleEditor?.scrollIntoView({ behavior: 'smooth', block: 'center' }); articleEditor?.focus(); });
articleEditor?.addEventListener('input', () => { if (workbenchSession) workbenchSession.article = articleEditor.value; });
renderChatThread(null);
renderOutline({});
syncWorkbenchModePicker();

async function postCreator(path, payload, signal, onAccepted) {
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
    return submitQueuedTask(taskTypes[path], taskPayload, signal, onAccepted);
  }
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...sharedApiPayload(), ...payload }),
    signal: signal || (path === '/api/viral-remix/analyze' ? AbortSignal.timeout(285000) : undefined),
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
      onAccepted?.(state.job);
      if (state.job.status === 'succeeded') return state.job.result;
      if (['failed', 'canceled'].includes(state.job.status)) throw new Error(state.job.error || '任务未完成');
    } finally {
      if (signal?.aborted) cancel();
    }
  }
}

function beginButton(button, label) {
  const original = button.innerHTML;
  const started = performance.now();
  if(button.nextElementSibling?.classList.contains('wait-elapsed'))button.nextElementSibling.remove();
  button.disabled = true;
  const status = document.createElement('p');status.className='wait-elapsed';status.setAttribute('role','status');
  button.after(status);
  const paint=()=>{const seconds=Math.floor((performance.now()-started)/1000);const time=`${Math.floor(seconds/60)}分${String(seconds%60).padStart(2,'0')}秒`;button.innerHTML=`<span class="button-spinner"></span>${esc(label)} · ${time}`;status.textContent=label.includes('拆解') ? `已等待 ${time} · 参考范围1—4分钟，含视觉分析、方案组织及必要的数据核实。${seconds>180?'耗时偏长，请勿重复提交。':''}` : `已等待 ${time}${label.includes('原创图')?' · 图片一般每张约30—120秒，多张按顺序处理。':''}`;};
  paint();const timer=setInterval(paint,1000);
  return () => { clearInterval(timer);status.textContent=`本次用时 ${((performance.now()-started)/1000).toFixed(1)} 秒`;button.disabled = false; button.innerHTML = original; window.lucide?.createIcons(); };
}

function renderSkillProgress(root, total) {
  root.insertAdjacentHTML('afterbegin', `<div class="generation-progress"><div><strong>正在生成图片</strong><span class="progress-copy">0 / ${total}</span><span class="image-elapsed" role="status">已耗时 0 秒</span></div><div class="progress-track"><i style="width:0%"></i></div><button class="cancel-generation" type="button">取消</button></div>`);
  return root.querySelector('.generation-progress');
}

let imageGenerationController = null;
async function generateSkillImages(tool, sessionId, cards, style, grid, onImage = null) {
  imageGenerationController?.abort();
  imageGenerationController = new AbortController();
  grid.parentElement.querySelectorAll('.generation-progress').forEach(el => el.remove());
  const progress = renderSkillProgress(grid.parentElement, cards.length);
  const started = Date.now();
  const elapsed = () => { progress.querySelector('.image-elapsed').textContent = `已耗时 ${Math.floor((Date.now()-started)/1000)} 秒`; };
  const timer = setInterval(elapsed, 1000);
  progress.querySelector('.cancel-generation').addEventListener('click', () => imageGenerationController.abort());
  try {
    for (let index = 0; index < cards.length; index += 1) {
      const data = await postCreator('/api/creator-tools/image', { tool, sessionId, card: cards[index], style }, imageGenerationController.signal, job => {
        progress.querySelector('strong').textContent = job.status === 'queued' ? '排队中，等待图片服务' : '正在生成图片';
      });
      onImage?.(data.image);
      const target = grid.querySelector(`[data-card-index="${data.image.index}"]`);
      if (target) {
        target.classList.add('generated');
        renderCardImage(target.querySelector('.card-image-slot'), data.image);
      }
      const done = index + 1;
      progress.querySelector('.progress-copy').textContent = `${done} / ${cards.length}`;
      progress.querySelector('.progress-track i').style.width = `${done / cards.length * 100}%`;
    }
    progress.classList.add('done');
    progress.querySelector('strong').textContent = '图片生成完成';
    progress.querySelector('.cancel-generation').remove();
    showToast(`已生成 ${cards.length} 张图片`);
    return true;
  } catch (error) {
    if (error.name === 'AbortError') {
      progress.querySelector('strong').textContent = '已取消生成';
      showToast('已取消后续图片生成', 'error');
    } else {
      progress.querySelector('strong').textContent = '生成中断';
      showToast(error.message, 'error');
    }
  } finally {
    clearInterval(timer); elapsed();
    progress.querySelector('.cancel-generation')?.remove();
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
  const imageButton = root.querySelector('#xhs-images');
  imageButton.textContent = `生成 ${cards.length} 张图片`;
  imageButton.hidden = cards.length === 0;
  const cardSection = root.querySelector('.creator-card-grid').closest('.result-section');
  cardSection.hidden = cards.length === 0;
  cardSection.querySelector('.result-section-title span').textContent = `${cards.length} 张`;
  imageButton.addEventListener('click', () => pkg.conversation_id
    ? window.dispatchEvent(new CustomEvent('creator-chat-send', {detail: {skill: 'xiaohongshu', message: '确认当前计划，生成全部未生成图片'}}))
    : generateSkillImages('xiaohongshu', pkg.session_id, cards, '真人贴纸爆款教程风，明亮蓝色创作者工作台，人物动作轮换', root.querySelector('.creator-card-grid')));
  renderConversationImages(root, pkg.images);
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
  const completed = new Set((plan.images || []).map(image => Number(image.index)));
  let pilotDone = cards.length > 0 && completed.has(Number(cards[0].index));
  const remaining = () => cards.filter(card => !completed.has(Number(card.index)));
  const buttonLabel = () => pilotDone ? `确认试图并生成剩余 ${remaining().length} 张` : '确认计划并生成第 1 张试图';
  root.innerHTML = `<div class="output-head"><div><span class="result-status pending">${cards.length && !remaining().length ? '图片已生成' : pilotDone ? '试图待确认' : '计划待确认'}</span><h2>${esc(plan.title)}</h2><p>${esc(plan.content_type_label)} · ${esc(plan.angle)}</p></div><button id="tie-images" class="primary-action compact" type="button">${buttonLabel()}</button></div>
    <div class="plan-summary"><div><span>画幅</span><strong>${esc(plan.ratio)}</strong></div><div><span>图片</span><strong>${cards.length} 张</strong></div><div><span>人物一致性</span><strong>${plan.portrait_enabled ? '已启用' : '未启用'}</strong></div></div>
    <section class="result-section"><div class="result-section-title"><strong>卡片计划</strong><span>先检查标题和画面，再确认生成</span></div><div class="creator-card-grid">${cards.map((card, position) => `<article class="creator-output-card" data-card-index="${Number(card.index)}"><div class="card-image-slot"><span>${String(card.index).padStart(2, '0')}</span><small>${position === 0 ? '首张试图 · 等待生成' : '等待生成'}</small></div><div class="creator-card-copy"><span>${position === 0 ? '封面 · 首张试图' : `内容卡片 ${String(card.index).padStart(2, '0')}`}</span><strong>${esc(card.overlay_text)}</strong><p><b>画面</b> ${esc(card.visual_subject)}</p><small>${esc([card.card_brief?.scene, card.card_brief?.action].filter(Boolean).join(' · '))}</small></div></article>`).join('')}</div></section>
    <section class="result-section"><div class="result-section-title"><strong>配套文案</strong><button class="copy-result" data-copy-target="tie-copy" type="button"><i data-lucide="copy"></i>复制</button></div><textarea id="tie-copy" class="result-editor compact">${esc(plan.copy || '')}</textarea><p class="cta-line">${esc(plan.cta || '')}</p></section>`;
  root.querySelector('#tie-images').hidden = cards.length === 0 || remaining().length === 0;
  root.querySelector('.plan-summary').hidden = cards.length === 0;
  root.querySelector('.creator-card-grid').closest('.result-section').hidden = cards.length === 0;
  root.querySelector('#tie-images').addEventListener('click', async event => {
    const selected = pilotDone ? remaining() : [cards[0]];
    if (!selected.length) return;
    if (plan.conversation_id) {
      const message = pilotDone ? '确认试图，生成剩余未生成的图片' : `确认当前卡片计划，只生成第 ${cards[0].index} 张试图`;
      window.dispatchEvent(new CustomEvent('creator-chat-send', {detail: {skill: 'tie-tu', message}}));
      return;
    }
    const button = event.currentTarget;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    button.textContent = '正在生成图片…';
    try {
    await generateSkillImages('tie-tu', plan.session_id, selected.map(card => ({...card, portrait_enabled: plan.portrait_enabled})), document.querySelector('#tie-style').value.trim(), root.querySelector('.creator-card-grid'), image => completed.add(Number(image.index)));
    } finally { button.disabled = false; button.removeAttribute('aria-busy'); button.textContent = buttonLabel(); }
    if (completed.size) {
      pilotDone = completed.has(Number(cards[0].index));
      button.hidden = !remaining().length;
      button.textContent = buttonLabel();
      root.querySelector('.result-status').textContent = remaining().length ? '试图待确认' : '图片已生成';
    }
  });
  renderConversationImages(root, plan.images);
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

function renderCardImage(slot, image) {
  const url = safeUrl(image.url);
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'card-image-preview';
  button.setAttribute('aria-label', `放大图片 ${image.index}`);
  const img = document.createElement('img'); img.src = url; img.alt = `图片 ${image.index}`;
  button.append(img);
  const download = document.createElement('a'); download.href = url;
  download.download = `card-${image.index}.png`; download.textContent = '下载图片';
  download.className = 'card-image-download';
  button.addEventListener('click', () => {
    const dialog = document.createElement('dialog'); dialog.className = 'card-image-lightbox';
    const close = document.createElement('button'); close.type = 'button'; close.textContent = '关闭';
    const large = img.cloneNode(); const save = download.cloneNode(true);
    const actions = document.createElement('div'); actions.append(save, close);
    dialog.append(large, actions); document.body.append(dialog);
    close.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => { if (event.target === dialog) dialog.close(); });
    dialog.addEventListener('close', () => { dialog.remove(); button.focus(); });
    dialog.showModal(); close.focus();
  });
  slot.replaceChildren(button, download);
}

function renderConversationImages(root, images = []) {
  for (const image of images) {
    const slot = root.querySelector(`[data-card-index="${Number(image.index)}"] .card-image-slot`);
    if (!slot) continue;
    renderCardImage(slot, image);
  }
}

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

const viralRemixForm = document.querySelector('#viral-remix-form');
const viralRemixImage = document.querySelector('#viral-remix-image');
const viralRemixPreview = document.querySelector('#viral-remix-preview');
let viralRemixPreviewUrl = '';
let viralFiles = [];
function paintViralFiles() {
  viralRemixPreview.replaceChildren(); viralRemixPreview.hidden = !viralFiles.length;
  viralFiles.forEach((file,index) => {
    const row = document.createElement('div'); row.className = 'viral-file';
    const img = document.createElement('img'); const url = URL.createObjectURL(file); img.src=url; img.onload=()=>URL.revokeObjectURL(url); img.alt=`参考图 ${index+1}`;
    const label=document.createElement('span');label.textContent=`${index+1}. ${file.name}`;
    const remove=document.createElement('button');remove.type='button';remove.textContent='移除';remove.onclick=()=>{viralFiles.splice(index,1);paintViralFiles();};
    row.append(img,label,remove);viralRemixPreview.append(row);
  });
}

function resetViralRemixImage() {
  if (viralRemixPreviewUrl) URL.revokeObjectURL(viralRemixPreviewUrl);
  viralRemixPreviewUrl = '';
  viralFiles.length = 0;
  if (viralRemixImage) viralRemixImage.value = '';
  if (viralRemixPreview) { viralRemixPreview.hidden = true; viralRemixPreview.replaceChildren(); }
}

viralRemixImage?.addEventListener('change', () => {
  const files = [...(viralRemixImage.files || [])];
  if(viralFiles.length+files.length>8){showToast('最多上传8张参考图','error');viralRemixImage.value='';return;}
  if(files.some(f=>f.size>10*1024*1024 || !['image/png','image/jpeg','image/webp'].includes(f.type))){showToast('请选择每张小于10MB的PNG、JPG或WebP','error');viralRemixImage.value='';return;}
  viralFiles.push(...files);viralRemixImage.value='';paintViralFiles();
});
document.querySelector('#viral-remix-clear')?.addEventListener('click', resetViralRemixImage);
let remixSelectPanel = null;
let remixRenderedSession = null;
let remixRenderedOwner = null;
// 生成原创图时立刻切到「成图交付」并在该面板里跑计时器，避免停在拆解报告看不到进度。
function startRemixOutputWait(label) {
  const root = document.querySelector('#viral-remix-result');
  const output = document.querySelector('#remix-output-panel');
  if (!root || !output) return () => {};
  remixSelectPanel?.(2);
  output.querySelector('.remix-output-placeholder')?.remove();
  let box = output.querySelector('.remix-output-wait');
  if (!box) {
    box = document.createElement('div');
    box.className = 'remix-output-wait';
    box.innerHTML = '<h3 class="remix-wait-title"></h3><p class="wait-elapsed" role="status"></p><p class="remix-wait-hint">生成完成后这里会显示成图、配文方向与标签，可直接下载。</p>';
    output.prepend(box);
  }
  box.querySelector('.remix-wait-title').textContent = label;
  const status = box.querySelector('.wait-elapsed');
  const started = performance.now();
  const paint = () => {
    const seconds = Math.floor((performance.now() - started) / 1000);
    status.textContent = `已等待 ${Math.floor(seconds / 60)}分${String(seconds % 60).padStart(2, '0')}秒 · 图片一般每张约30—120秒，多张按顺序处理。`;
  };
  paint();
  const timer = setInterval(paint, 1000);
  root.scrollIntoView({ block: 'start', behavior: 'smooth' });
  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    clearInterval(timer);
    output.querySelector('.remix-output-wait')?.remove();
    if (!output.querySelector('.viral-generated')) {
      const placeholder = document.createElement('div');
      placeholder.className = 'remix-output-placeholder';
      placeholder.innerHTML = '<h3>成图与配文会放在这里</h3><p>选择翻新方案后生成，完成后可下载图片、查看配文方向和标签。</p>';
      output.append(placeholder);
    }
  };
}
function renderViralRemix(result, sessionId) {
  const remixOwner = currentAccount?.id;
  remixRenderedOwner = remixOwner || null;
  remixRenderedSession = sessionId || null;
  const remixKey = remixOwner ? `viral-remix-draft:${remixOwner}` : null;
  let saved = {};
  try { saved = remixKey ? JSON.parse(localStorage.getItem(remixKey)||'{}') : {}; } catch {}
  if(saved.sessionId !== sessionId) saved = {};
  const storeDraft = extra => {
    if(!remixKey || currentAccount?.id !== remixOwner) return;
    saved = {...saved,result,sessionId,...extra,updatedAt:Date.now()};
    try {localStorage.setItem(remixKey,JSON.stringify(saved));} catch {showToast('浏览器存储空间不足，本次方案无法自动保存','error');}
  };
  storeDraft({});
  document.querySelector('#viral-remix-empty').hidden = true;
  const root = document.querySelector('#viral-remix-result');
  root.hidden = false;
  const analysis = result.analysis || {};
  const rows = [['视觉锚点', analysis.visual_anchor], ['信息层级', analysis.hierarchy], ['构图', analysis.composition], ['色彩', analysis.palette], ['情绪', analysis.emotion], ['钩子', analysis.hook]];
  rows.push(['质感',analysis.texture],['平台表达',analysis.platform_language]);
  root.innerHTML = `<article class="viral-result-card"><span class="tag">第 2/5 步 · 结构拆解</span><h2>${esc(result.content_guess || '对标图结构')}</h2><div class="viral-analysis">${rows.map(([label, text]) => `<div><b>${esc(label)}</b><span>${esc(text || '未识别')}</span></div>`).join('')}</div><p><b>可补的信息：</b>${esc(result.missing || '未提供')}</p></article><section class="viral-ideas"><div class="result-section-title"><strong>第 3/5 步 · 选择翻新方向</strong><span>保留结构，不复用画面</span></div>${(result.ideas || []).map(idea => `<article class="viral-idea"><span class="idea-id">${esc(idea.id)}</span><h3>${esc(idea.name)}</h3><p>${esc(idea.summary)}</p><dl><div><dt>保留</dt><dd>${esc(idea.keep)}</dd></div><div><dt>改变</dt><dd>${esc(idea.change)}</dd></div><div><dt>为什么不撞</dt><dd>${esc(idea.why_original)}</dd></div></dl><button type="button" class="primary-action viral-generate" data-idea="${esc(idea.id)}">选这版，生成原创图 →</button></article>`).join('')}</section>`;
  root.querySelectorAll('.viral-generate').forEach(button => button.addEventListener('click', async () => {
    const idea = (result.ideas || []).find(item => item.id === button.dataset.idea);
    if (!idea) return;
    const finish = beginButton(button, '正在生成原创图…');
    storeDraft({pending:true,selectedIdea:idea.id});
    const stopWaiting = startRemixOutputWait(`正在生成第 4/5 步原创图${idea.name ? `（${idea.name}）` : ''}`);
    try {
      const choices={track:root.querySelector('[name=remix-track]')?.value,emotion:root.querySelector('[name=remix-emotion]')?.value,boundaries:root.querySelector('[name=remix-boundaries]')?.value};
      const data = await postCreator('/api/viral-remix/image', { sessionId, idea: {...idea,choices,copy_directions:result.copy_directions,tags:result.tags} });
      const image = data.image;
      storeDraft({generated:[...(saved.generated||[]),image],pending:false});
      const all=image.images?.length?image.images:[image];
      all.map((extra,position)=>({extra,ordinal:Number(extra.index)||position+1}))
        .sort((a,b)=>b.ordinal-a.ordinal)
        .forEach(({extra,ordinal})=>{
          const name=all.length>1?`爆款贴图复刻-${idea.id}-${ordinal}.png`:`爆款贴图复刻-${idea.id}.png`;
          const label=all.length>1?`下载第 ${ordinal} 张`:'下载图片';
          const card=document.createElement('article');card.className='viral-generated';
          card.innerHTML=`<span class="tag">第 4/5 步 · 原创成图${all.length>1?` · ${ordinal}/${all.length}`:''}</span><img src="${safeUrl(extra.url)}" alt="${esc(idea.headline||'原创贴图')} ${ordinal}"/><div><strong>${esc(idea.headline||'')}</strong><a href="${safeUrl(extra.url)}" download="${esc(name)}">${label}</a></div>`;
          output.append(card);
        });
      const delivery=document.createElement('pre');delivery.className='viral-delivery';delivery.textContent=JSON.stringify({提示词:(image.images||[image]).map(i=>i.prompt),配文方向:image.copy_directions||result.copy_directions,标签:image.tags||result.tags,检查:(image.images||[image]).map(i=>({通过:i.check_passed,报告:i.check}))},null,2);output.append(delivery);
      stopWaiting();
      output.hidden = false;
      remixSelectPanel?.(2);
      root.scrollIntoView({block:'start',behavior:'smooth'});
      showToast('原创图已生成；参考图没有进入生图请求。');
    } catch (error) { showToast(error.message, 'error'); } finally { stopWaiting(); finish(); }
  }));
  const context=document.createElement('section');context.className='viral-result-card';
  context.innerHTML=`<h3>顺序与逐页分析</h3><p>${esc((result.order||[]).join(' → '))} · ${esc(result.order_reason||'单图，无需排序')}</p><p>${esc(JSON.stringify(result.pages||[]))}</p><p>${esc(result.verification?.message||'待核实')}</p><h3>确认创作方向</h3><label>赛道<select name="remix-track">${['情感关系','育儿成长','赚钱职场','生活消费','娱乐搞笑'].map(t=>`<option>${t}</option>`).join('')}</select></label><label>想让读者感到<select name="remix-emotion">${['被理解','被点醒','被教会','被逗笑','有点急'].map(t=>`<option>${t}</option>`).join('')}</select></label><label>画面禁区<select name="remix-boundaries"><option>不出现真人正脸</option><option>不出现品牌和产品</option><option>不出现特定人物或同行</option><option>无额外禁区</option></select></label><p>确认后点选下方 A/B/C 方案。文字与画面由 GPT Image 一体生成，整组保持相同视觉方向。</p>`;
  root.querySelector('.viral-ideas').before(context);
  if(result.claims?.length){const verify=document.createElement('button');verify.type='button';verify.className='remix-next';verify.textContent='单独核实参考图中的数字';const info=document.createElement('p');info.textContent=result.verification?.message||'数字待核实';context.append(info,verify);verify.onclick=async()=>{const finish=beginButton(verify,'正在核实数字…');try{const state=await postCreator('/api/viral-remix/verify',{claims:result.claims.slice(0,3).map(c=>typeof c==='string'?c:JSON.stringify(c))});info.textContent=`${state.message} · 用时${state.seconds}秒`;result.verification=state;storeDraft({});}catch(e){info.textContent=`核实未完成：${e.message}；生成仍会避开这些数字。`;}finally{finish();}};}
  const rawPages=context.querySelectorAll(':scope > p')[1];
  if(rawPages){const pages=document.createElement('div');pages.className='remix-page-list';(result.pages||[]).forEach((page,index)=>{const item=document.createElement('article');item.innerHTML=`<span class="tag">参考图 ${esc(page.page||index+1)}</span><h4>${esc(page.role||'内容页')}</h4><p>信息密度：${esc(page.density||'待判断')}</p><p>${esc(page.missing||'未发现明显缺口')}</p>`;pages.append(item);});rawPages.replaceWith(pages);}
  const report=document.createElement('div');report.className='remix-panel';report.id='remix-report-panel';report.append(root.querySelector('.viral-result-card'),context);
  const ideas=root.querySelector('.viral-ideas');ideas.classList.add('remix-panel');ideas.id='remix-ideas-panel';
  const choices=document.createElement('div');choices.className='remix-choices';
  let choiceNode=[...context.querySelectorAll('h3')].find(h=>h.textContent==='确认创作方向');
  while(choiceNode){const next=choiceNode.nextSibling;choices.append(choiceNode);choiceNode=next;}ideas.prepend(choices);
  const output=document.createElement('div');output.className='remix-panel';output.id='remix-output-panel';output.innerHTML='<div class="remix-output-placeholder"><h3>成图与配文会放在这里</h3><p>选择翻新方案后生成，完成后可下载图片、查看配文方向和标签。</p></div>';
  const tabs=document.createElement('div');tabs.className='remix-result-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','创作结果');
  const panels=[report,ideas,output];
  const selectPanel=index=>{panels.forEach((p,i)=>p.hidden=i!==index);[...tabs.children].forEach((b,i)=>{b.setAttribute('aria-selected',String(i===index));b.tabIndex=i===index?0:-1;});};
  remixSelectPanel=selectPanel;
  ['拆解报告','翻新方案','成图交付'].forEach((label,index)=>{const b=document.createElement('button');b.type='button';b.textContent=`0${index+1} ${label}`;b.setAttribute('role','tab');b.setAttribute('aria-controls',panels[index].id);b.onclick=()=>selectPanel(index);b.onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const next=(index+(e.key==='ArrowRight'?1:2))%3;selectPanel(next);tabs.children[next].focus();}};tabs.append(b);});
  root.replaceChildren(tabs,...panels);selectPanel(0);
  if(saved.choices) for(const [key,value] of Object.entries(saved.choices)){const field=root.querySelector(`[name="remix-${key}"]`);if(field)field.value=value;}
  root.querySelectorAll('.remix-choices select').forEach(field=>field.addEventListener('change',()=>storeDraft({choices:{track:root.querySelector('[name=remix-track]')?.value,emotion:root.querySelector('[name=remix-emotion]')?.value,boundaries:root.querySelector('[name=remix-boundaries]')?.value}})));
  root.querySelectorAll('.viral-generate').forEach(button=>button.addEventListener('click',()=>storeDraft({selectedIdea:button.dataset.idea})));
  for(const generated of saved.generated||[]){output.querySelector('.remix-output-placeholder')?.remove();for(const image of generated.images||[generated]){const card=document.createElement('article');card.className='viral-generated';card.innerHTML=`<img src="${safeUrl(image.url)}" alt="已保存原创图 ${Number(image.index)||1}"><a href="${safeUrl(image.url)}" download>下载图片</a>`;output.append(card);}}
  if(saved.generated?.length)selectPanel(2);
  else if(saved.pending){const note=document.createElement('p');note.className='remix-output-pending';note.textContent='上次的原创图生成没有完成，重新点选下面的方案即可再次生成。';output.prepend(note);selectPanel(2);}
  if(result.timings){const duration=document.createElement('p');duration.className='wait-elapsed';duration.textContent=`拆解总计 ${result.timings.total_seconds} 秒 · 视觉与方案 ${result.timings.vision_seconds} 秒 · 数字核实 ${result.timings.verification_seconds||0} 秒`;report.prepend(duration);}
  const next=document.createElement('button');next.type='button';next.className='remix-next';next.textContent='查看三种翻新方案 →';next.onclick=()=>{selectPanel(1);root.scrollIntoView({block:'start',behavior:'smooth'});};report.append(next);
}
window.addEventListener('account-changed',()=>{
  const root=document.querySelector('#viral-remix-result');
  if(!root)return;
  // 同一账号重复触发的 account-changed（切窗口、钱包刷新等）不要重绘，
  // 否则会把正在看的面板重置回「拆解报告」。
  if(currentAccount?.id && currentAccount.id===remixRenderedOwner && remixRenderedSession) return;
  root.replaceChildren();root.hidden=true;document.querySelector('#viral-remix-empty').hidden=false;
  remixSelectPanel=null;remixRenderedSession=null;remixRenderedOwner=currentAccount?.id||null;
  if(!currentAccount?.id)return;
  try{const draft=JSON.parse(localStorage.getItem(`viral-remix-draft:${currentAccount.id}`)||'null');if(draft?.result&&draft.sessionId)renderViralRemix(draft.result,draft.sessionId);}catch{}
});
viralRemixForm?.addEventListener('submit', async event => {
  event.preventDefault();
  if (!viralFiles.length) {showToast('请先选择1—8张参考图','error');return;}
  const button = document.querySelector('#viral-remix-start');
  const finish = beginButton(button, '正在拆解图片结构…');
  try {
    const imageData = await Promise.all(viralFiles.map(file=>new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = () => reject(new Error('图片读取失败')); reader.readAsDataURL(file); })));
    const sessionId = crypto.randomUUID().replaceAll('-', '');
    const data = await postCreator('/api/viral-remix/analyze', { imageData, goal: document.querySelector('#viral-remix-goal').value.trim() });
    renderViralRemix(data.result, sessionId);
  } catch (error) { showToast(error.message, 'error'); } finally { finish(); }
});

const viewMap = {
  home: homePage,
  diagnose: diagnosePage,
  workbench,
  'wechat-plus': document.querySelector('#wechat-plus'),
  'one-click-writing': document.querySelector('#one-click-writing'),
  xiaohongshu: xiaohongshuPage,
  'tie-tu': tieTuPage,
  'viral-remix': viralRemixPage,
  'xhs-extract': xhsExtractPage,
  'douyin-extract': douyinExtractPage,
  'hit-detector': hitDetectorPage,
  morning: morningGenerator,
  report: reportRoot,
  market: document.querySelector('#market'),
  bookshelf: document.querySelector('#bookshelf'),
  hotspots: document.querySelector('#hotspots'),
  lowfans: document.querySelector('#lowfans'),
};

const viewTitles = {
  home: '宇宙第一工作台',
  workbench: '公众号创作',
  'wechat-plus': '公众号创作 Plus',
  'one-click-writing': '公众号一键成文',
  xiaohongshu: '小红书创作',
  'tie-tu': '微信贴图号',
  'viral-remix': '爆款贴图复刻',
  'xhs-extract': '小红书内容提取',
  'douyin-extract': '抖音内容提取',
  'hit-detector': '爆文检测',
  morning: '早安祝福',
  report: '诊断报告',
  market: 'AI 超市',
  bookshelf: 'AI 书架',
  hotspots: '热点广场',
  lowfans: '低粉爆文',
};

function pathToView(path) {
  const p = String(path || '').replace(/^\/+|\/+$/g, '');
  if (!p) return 'home';
  if (p === 'morning-generator') return 'morning';
  return Object.prototype.hasOwnProperty.call(viewMap, p) ? p : 'home';
}

window.AppNav = { setActiveView };

function setActiveView(view, updateHash = false) {
  Object.entries(viewMap).forEach(([name, element]) => { if (element) element.hidden = name !== view; });
  document.querySelectorAll('.app-tabs [data-view]').forEach(item => item.classList.toggle('active', item.dataset.view === view));
  appShell?.classList.toggle('workbench-active', view !== 'home' && view !== 'diagnose' && view !== 'report' && view !== 'market' && view !== 'hotspots' && view !== 'lowfans');
  document.body.classList.toggle('market-body', view === 'market');
  document.body.classList.toggle('hotspots-body', view === 'hotspots');
  document.body.classList.toggle('lowfans-body', view === 'lowfans');
  if (view === 'market') window.MarketView?.ensureLoaded?.();
  if (view === 'wechat-plus') window.WechatPlus?.ensureLoaded?.();
  if (view === 'bookshelf') {
    const frame=document.querySelector('#bookshelf-frame');
    if(frame && !frame.hasAttribute('src'))frame.src='/bookshelf?embed=1';
  }
  if (view === 'hotspots') window.HotspotsView?.ensureLoaded?.();
  if (view === 'lowfans') window.LowfansView?.ensureLoaded?.();
  // 低粉爆文「去写这篇」用 /workbench?topic=<标题> 把选题带进创作台：
  // 填进输入框后立刻清掉参数，避免刷新时重复覆盖用户自己改过的内容。
  if (view === 'workbench') {
    const params = new URLSearchParams(location.search);
    const topic = params.get('topic');
    if (topic) {
      const box = document.querySelector('#workbench-topic');
      if (box && !box.value.trim()) {
        box.value = topic;
        box.dispatchEvent(new Event('input', { bubbles: true }));
        box.focus();
      }
      params.delete('topic');
      params.delete('type');
      const rest = params.toString();
      history.replaceState(null, '', '/workbench' + (rest ? '?' + rest : ''));
    }
  }
  if (downloadButton) downloadButton.hidden = view !== 'report';
  if (view === 'one-click-writing') {
    const frame = document.querySelector('#one-click-writing-frame');
    if (frame && !frame.hasAttribute('src')) frame.src = frame.dataset.src;
  }
  if (view === 'morning') syncMorningApiKey();
  const commandTitle = document.querySelector('#command-title');
  if (commandTitle) commandTitle.textContent = viewTitles[view] || '宇宙第一工作台';
  if (updateHash && view !== 'report') {
    const url = view === 'home' ? '/' : `/${view === 'morning' ? 'morning-generator' : view}`;
    history.replaceState(null, '', url);
  }
  window.scrollTo({ top: 0, behavior: 'instant' });
}

document.querySelector('#command-settings')?.addEventListener('click', openWallet);

document.addEventListener('click', event => {
  const jump = event.target.closest('[data-view]');
  if (!jump || jump.closest('.app-tabs')) return;
  if (jump.matches('a') && (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0)) return;
  event.preventDefault();
  setActiveView(jump.dataset.view, true);
});

document.querySelectorAll('.app-tabs [data-view]').forEach(tab => tab.addEventListener('click', event => {
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0) return;
  event.preventDefault();
  setActiveView(tab.dataset.view, true);
}));

window.addEventListener('popstate', () => setActiveView(pathToView(location.pathname), false));

const initialView = pathToView(location.pathname);
setActiveView(initialView);
window.dispatchEvent(new Event('app-nav-ready'));
refreshConfigStatus();
paintWorkflow();
loadAccount();
window.lucide?.createIcons({ attrs: { 'stroke-width': 1.8 } });
