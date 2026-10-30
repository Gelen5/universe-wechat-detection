/* Registration-only Turnstile; a fresh single-use token for each submission. */
(() => {
  let siteKey = '', widget = null, token = '', currentAction = '', ready;
  let pendingResolve, pendingReject;
  const host = () => document.querySelector('#auth-challenge');
  function load() {
    if (ready) return ready;
    ready = new Promise((resolve, reject) => {
      window.universeTurnstileReady = resolve;
      const script = document.createElement('script');
      script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js?onload=universeTurnstileReady&render=explicit';
      script.async = true;
      script.onerror = () => { ready = null; reject(new Error('人机验证加载失败，请重试')); };
      document.head.append(script);
    });
    return ready;
  }
  async function render(action) {
    if (!siteKey) return;
    await load();
    if (currentAction === action && widget !== null) return;
    if (widget !== null) window.turnstile.remove(widget);
    token = ''; currentAction = action;
    const widgetHost = document.querySelector('#auth-challenge-widget');
    widget = window.turnstile.render(widgetHost, {
      sitekey: siteKey, action, theme: 'light', language: 'zh-CN', size: widgetHost.clientWidth < 300 ? 'compact' : 'flexible',
      callback: value => { token = value; pendingResolve?.(value); pendingResolve = pendingReject = null; },
      'expired-callback': () => { token = ''; },
      'error-callback': () => { token = ''; pendingReject?.(new Error('人机验证未完成，请重试')); pendingResolve = pendingReject = null; },
    });
  }
  window.AuthChallenge = {
    configure(config) { siteKey = config.turnstile_site_key || ''; },
    async mode(mode) {
      if (!host()) return;
      host().hidden = mode !== 'register' || !siteKey;
      if (mode === 'register' && siteKey) {
        try { await render('register_email'); }
        catch (error) { host().querySelector('.auth-verification-note').textContent = error.message; }
      }
    },
    async getToken(action) {
      if (!siteKey) return '';
      host().hidden = false;
      await render(action);
      if (token) return token;
      return new Promise((resolve, reject) => {
        pendingResolve = resolve; pendingReject = reject;
        setTimeout(() => {
          if (pendingResolve === resolve) { pendingResolve = pendingReject = null; reject(new Error('请完成人机验证后重试')); }
        }, 60000);
      });
    },
    reset() {
      token = '';
      if (widget !== null) window.turnstile.reset(widget);
    },
  };
})();
