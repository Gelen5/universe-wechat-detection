import { betterAuth } from 'better-auth';
import { emailOTP } from 'better-auth/plugins';
import { hashPassword, verifyPassword } from 'better-auth/crypto';
import { pbkdf2, timingSafeEqual, randomUUID, createHash, randomBytes, createCipheriv, createDecipheriv } from 'node:crypto';
import { promisify } from 'node:util';
import disposableDomains from 'disposable-email-domains' with {type:'json'};

const derive = promisify(pbkdf2);
const disposable = new Set(disposableDomains);
export class PublicError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function verifyCompatiblePassword({password, hash}) {
  if (!hash.startsWith('pbkdf2_sha256$')) return verifyPassword({password, hash});
  const [algorithm, iterations, salt, expected] = hash.split('$');
  if (algorithm !== 'pbkdf2_sha256' || !/^\d+$/.test(iterations) || Number(iterations) > 2_000_000 ||
      !/^[a-f0-9]{32}$/i.test(salt || '') || !/^[a-f0-9]{64}$/i.test(expected || '')) return false;
  const actual = await derive(password, Buffer.from(salt, 'hex'), Number(iterations), 32, 'sha256');
  return timingSafeEqual(actual, Buffer.from(expected, 'hex'));
}

export function createIdentity({database, redis, legacyExists, syncLegacy, env = process.env, fetcher = fetch}) {
  const baseURL = env.BETTER_AUTH_URL || 'http://localhost:8000';
  const ticketKey = createHash('sha256').update('registration-link:' + env.BETTER_AUTH_SECRET).digest();
  const linkKey = token => 'identity:link:' + createHash('sha256').update(token).digest('hex');
  function seal(value) {
    const iv = randomBytes(12), cipher = createCipheriv('aes-256-gcm',ticketKey,iv);
    const data=Buffer.concat([cipher.update(JSON.stringify(value)),cipher.final()]);
    return Buffer.concat([iv,cipher.getAuthTag(),data]).toString('base64url');
  }
  function unseal(value) {
    try {
      const data=Buffer.from(value,'base64url'),cipher=createDecipheriv('aes-256-gcm',ticketKey,data.subarray(0,12));
      cipher.setAuthTag(data.subarray(12,28));
      return JSON.parse(Buffer.concat([cipher.update(data.subarray(28)),cipher.final()]).toString());
    } catch { throw new PublicError(403,'验证链接已失效，请重新获取验证码'); }
  }
  async function readLink(token) {
    if (!/^[a-f0-9]{64}$/.test(token || '')) throw new PublicError(403,'验证链接无效');
    const value=await redis.get(linkKey(token));
    if(!value)throw new PublicError(403,'验证链接已失效，请重新获取验证码');
    return unseal(value);
  }
  async function deliverOTP({email, otp}) {
    if (!env.RESEND_API_KEY || !env.RESEND_FROM) throw new PublicError(503, '邮件服务尚未配置');
    const token=randomBytes(32).toString('hex');
    await redis.set(linkKey(token),seal({email,otp}),{EX:1800});
    const link=new URL(baseURL);link.pathname='/';link.search='';link.hash='register='+token;
    const response = await fetcher('https://api.resend.com/emails', {
      method: 'POST', headers: {'Authorization': `Bearer ${env.RESEND_API_KEY}`, 'Content-Type': 'application/json'},
      body: JSON.stringify({from: env.RESEND_FROM, to: [email], subject: '宇宙第一工作台注册验证码',
        text: `你的注册验证码是 ${otp}，30 分钟内有效。最多尝试 5 次。请勿向他人透露验证码。\n也可打开备用验证链接，然后设置密码完成注册：\n${link.href}\n链接与验证码使用相同的验证凭证，只能成功验证一次。\n如果不是你本人操作，请忽略。`}),
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw new PublicError(503, '验证码邮件发送失败，请稍后重试');
    const accepted = await response.json();
    if (typeof accepted.id !== 'string' || !accepted.id) throw new PublicError(503, '邮件服务未确认接收，请稍后重试');
  }
  const auth = betterAuth({
    database, baseURL, basePath: '/api/auth', secret: env.BETTER_AUTH_SECRET,
    trustedOrigins: [new URL(baseURL).origin],
    user: {modelName: 'auth_user'},
    session: {modelName: 'auth_session', expiresIn: 7 * 86400, cookieCache: {enabled: false}},
    account: {modelName: 'auth_account'},
    verification: {modelName: 'auth_verification'},
    advanced: {database: {generateId: () => randomUUID().replaceAll('-', '')}},
    emailAndPassword: {enabled: true, disableSignUp: true,
      password: {hash: hashPassword, verify: verifyCompatiblePassword}},
    plugins: [emailOTP({otpLength: 6, expiresIn: 1800, allowedAttempts: 5, storeOTP: 'hashed',
      sendVerificationOTP: deliverOTP,
    })],
  });

  function emailValue(value) {
    const email = String(value || '').trim().toLowerCase();
    if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) throw new PublicError(422, '请输入有效邮箱');
    const domain = email.split('@')[1];
    const denied = (env.AUTH_BLOCKED_EMAIL_DOMAINS || '').split(',').map(d => d.trim().toLowerCase()).filter(Boolean);
    const allowed = (env.AUTH_ALLOWED_EMAIL_DOMAINS || '').split(',').map(d => d.trim().toLowerCase());
    const parents = domain.split('.').map((_,i)=>domain.split('.').slice(i).join('.'));
    if (!allowed.includes(domain) && (parents.some(d=>disposable.has(d)) || denied.some(d => domain === d || domain.endsWith('.' + d))))
      throw new PublicError(422, '请使用长期有效的邮箱注册');
    return email;
  }
  const digest = value => createHash('sha256').update(value).digest('hex');
  const headersFor = cookie => new Headers({origin: new URL(baseURL).origin, ...(cookie ? {cookie} : {})});
  async function exclusive(email, fn) {
    const key = 'identity:lock:' + digest(email), token = randomUUID();
    if (!await redis.set(key, token, {NX: true, EX: 60})) throw new PublicError(429, '正在处理，请稍后重试');
    try { return await fn(); }
    finally { await redis.eval("if redis.call('GET',KEYS[1]) == ARGV[1] then return redis.call('DEL',KEYS[1]) end return 0", {keys:[key],arguments:[token]}); }
  }
  async function checkTurnstile(token, ip, action) {
    if (env.TURNSTILE_ENABLED !== '1') return;
    if (!env.TURNSTILE_SECRET_KEY || !env.TURNSTILE_SITE_KEY) throw new PublicError(503, '人机验证服务尚未配置');
    if (!token || token.length > 2048) throw new PublicError(403, '请先完成人机验证');
    let result;
    try {
      const response = await fetcher('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({secret:env.TURNSTILE_SECRET_KEY,response:token,...(ip ? {remoteip:ip} : {})}),
        signal:AbortSignal.timeout(10000),
      });
      if (!response.ok) throw Error('validation unavailable');
      result = await response.json();
    } catch { throw new PublicError(503, '人机验证暂不可用，请重试'); }
    if (!result.success || result.hostname !== new URL(baseURL).hostname || result.action !== action)
      throw new PublicError(403, '人机验证失败或已过期，请重试');
  }
  async function unpack(response) {
    const data = await response.json();
    if (!response.ok) throw new PublicError(response.status, response.status === 401 ? '邮箱、密码或验证码不正确' : '认证未完成，请检查验证码或重新获取');
    return {data, cookies:response.headers.getSetCookie()};
  }
  return {
    auth,
    config: () => ({email_verification_required:true, auth_engine:'better-auth', turnstile_site_key:env.TURNSTILE_ENABLED === '1' ? env.TURNSTILE_SITE_KEY || '' : ''}),
    async linkInfo(body) {return {email:(await readLink(body.registration_token)).email};},
    async sendCode(body) {
      const email = emailValue(body.email);
      await checkTurnstile(body.turnstile_token, body.ip, 'register_email');
      return exclusive(email, async () => {
        // Registration codes never double as an existing-account password reset.
        if (await legacyExists(email) || await (await auth.$context).internalAdapter.findUserByEmail(email))
          throw new PublicError(409, '该邮箱已注册，请直接登录');
        const key = 'identity:cooldown:' + digest(email);
        if (!await redis.set(key, '1', {NX:true,EX:60})) throw new PublicError(429, '请 60 秒后再获取验证码');
        try {
          // The standard send endpoint intentionally swallows background email
          // errors. Await delivery ourselves so a provider failure cannot show
          // "sent" in the registration UI. Generation/storage remain Better Auth.
          const otp = await auth.api.createVerificationOTP({body:{email,type:'sign-in'},headers:headersFor()});
          await deliverOTP({email,otp});
        }
        catch (error) { await redis.del(key); throw error; }
        return {status:'success'};
      });
    },
    async register(body) {
      const email = emailValue(body.email);
      if (typeof body.password !== 'string' || body.password.length < 8 || body.password.length > 128)
        throw new PublicError(422, '密码长度需要为 8—128 位');
      await checkTurnstile(body.turnstile_token, body.ip, 'register');
      return exclusive(email, async () => {
        if (await legacyExists(email) || await (await auth.$context).internalAdapter.findUserByEmail(email))
          throw new PublicError(409, '该邮箱已注册，请直接登录');
        let otp=body.email_code || '';
        if(body.registration_token) {
          const link=await readLink(body.registration_token);
          if(link.email!==email)throw new PublicError(403,'验证链接与邮箱不匹配');
          otp=link.otp;
        }
        const result = await unpack(await auth.api.signInEmailOTP({body:{email,otp,name:String(body.display_name || email.split('@')[0]).slice(0,40)},headers:headersFor(),asResponse:true}));
        if(body.registration_token)await redis.del(linkKey(body.registration_token));
        const cookie = result.cookies.map(v => v.split(';')[0]).join('; ');
        try { await auth.api.setPassword({body:{newPassword:body.password},headers:headersFor(cookie)}); }
        catch (error) {
          await auth.api.signOut({headers:headersFor(cookie)});
          throw error;
        }
        return {user:result.data.user,cookies:result.cookies};
      });
    },
    async login(body) {
      const email = String(body.email || '').trim().toLowerCase();
      // Covers an old-service registration that raced the initial import.
      if (syncLegacy && !await (await auth.$context).internalAdapter.findUserByEmail(email)) await syncLegacy(email);
      const result = await unpack(await auth.api.signInEmail({body:{email,password:body.password},headers:headersFor(),asResponse:true}));
      return {user:result.data.user,cookies:result.cookies};
    },
    async session(body) {
      const result = await auth.api.getSession({headers:headersFor(body.cookie)});
      return {user:result?.user || null};
    },
    async logout(body) {
      const result = await unpack(await auth.api.signOut({headers:headersFor(body.cookie),asResponse:true}));
      return {cookies:result.cookies};
    },
  };
}
