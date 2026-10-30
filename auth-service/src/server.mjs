import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';
import { runtime } from './runtime.mjs';
import { PublicError } from './identity.mjs';
import { pathToFileURL } from 'node:url';

export function buildServer({identity,pool,redis,bridgeSecret}) {
const secret = Buffer.from(bridgeSecret);
const routes = new Map([['/config',()=>identity.config()],['/link-info',body=>identity.linkInfo(body)],['/send-code',body=>identity.sendCode(body)],
  ['/register',body=>identity.register(body)],['/login',body=>identity.login(body)],
  ['/session',body=>identity.session(body)],['/logout',body=>identity.logout(body)]]);
const server = createServer(async (req,res) => {
  res.setHeader('Content-Type','application/json'); res.setHeader('Cache-Control','no-store');
  if (req.method === 'GET' && req.url === '/health') {
    try { await pool.query('SELECT 1'); await redis.ping(); res.end('{"status":"ready"}'); }
    catch { res.statusCode=503;res.end('{"status":"unavailable"}'); }
    return;
  }
  const supplied = Buffer.from(String(req.headers['x-auth-bridge-secret'] || ''));
  if (supplied.length !== secret.length || !timingSafeEqual(supplied,secret)) { res.statusCode=403;res.end('{}');return; }
  const route=routes.get(req.url);
  if (req.method !== 'POST' || !route) {res.statusCode=404;res.end('{}');return;}
  try {
    let raw='';
    for await (const chunk of req) {raw+=chunk;if(Buffer.byteLength(raw)>16384)throw new PublicError(413,'请求过大');}
    const body=JSON.parse(raw || '{}');
    const result=await route(body);
    res.end(JSON.stringify(result));
  } catch(error) {
    // Never echo provider responses, credentials, cookies or OTPs.
    res.statusCode=error instanceof PublicError ? error.status : 503;
    res.end(JSON.stringify({detail:error instanceof PublicError ? error.message : '认证服务暂不可用，请稍后重试'}));
  }
});
server.requestTimeout=30000;
return server;
}
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const resources=await runtime();
  buildServer({...resources,bridgeSecret:process.env.AUTH_BRIDGE_SECRET}).listen(Number(process.env.PORT || 3001),'0.0.0.0');
}
