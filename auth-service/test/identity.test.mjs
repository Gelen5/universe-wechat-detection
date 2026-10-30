import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {getMigrations} from 'better-auth/db/migration';
import {pbkdf2Sync} from 'node:crypto';
import {createIdentity, verifyCompatiblePassword} from '../src/identity.mjs';

class MemoryRedis {
  values=new Map();
  async get(k) {return this.values.get(k);}
  async set(k,v,opts={}) { if(opts.NX && this.values.has(k))return null;this.values.set(k,v);return 'OK'; }
  async del(k) {return this.values.delete(k);}
  async eval(s,{keys,arguments:args}) {if(this.values.get(keys[0])===args[0])this.values.delete(keys[0]);}
}
async function setup(extra={}) {
  const database=new DatabaseSync(':memory:');
  const sent=[];
  const env={BETTER_AUTH_URL:'http://localhost:8000',BETTER_AUTH_SECRET:'test-secret-at-least-32-characters-long-123',RESEND_API_KEY:'test-only',RESEND_FROM:'test@example.test',...extra.env};
  const redis=new MemoryRedis();
  const identity=createIdentity({database,redis,legacyExists:async()=>false,env,
    fetcher:async(url,opts)=>{sent.push(JSON.parse(opts.body));return new Response(JSON.stringify({id:'test-message'}),{status:200});},...extra});
  await (await getMigrations(identity.auth.options)).runMigrations();
  return {identity,database,redis,sent};
}
const codeFrom = sent => sent[0].text.match(/\b\d{6}\b/)[0];
const cookieFrom = result => result.cookies.map(c=>c.split(';')[0]).join('; ');

test('real Better Auth OTP creates verified identity, password login and session revocation', async()=>{
  const {identity,database,sent}=await setup();
  await identity.sendCode({email:'New@Example.test'});
  assert.equal(sent.length,1);
  assert.deepEqual(sent[0].to,['new@example.test']);
  assert.equal(database.prepare('SELECT count(*) n FROM auth_user').get().n,0);
  const otp=codeFrom(sent);
  const record=database.prepare('SELECT value FROM auth_verification').get();
  assert.ok(!record.value.includes(otp));
  const registered=await identity.register({email:'new@example.test',email_code:otp,password:'LongPassword123',display_name:'新用户'});
  assert.equal(registered.user.emailVerified,true);
  assert.ok(registered.cookies.some(c=>c.includes('HttpOnly')));
  const login=await identity.login({email:'new@example.test',password:'LongPassword123'});
  assert.equal(login.user.id,registered.user.id);
  assert.equal((await identity.session({cookie:cookieFrom(login)})).user.id,registered.user.id);
  await identity.logout({cookie:cookieFrom(login)});
  assert.equal((await identity.session({cookie:cookieFrom(login)})).user,null);
  await assert.rejects(identity.register({email:'new@example.test',email_code:otp,password:'LongPassword123'}));
  database.close();
});

test('wrong OTPs hit five-attempt gate, expired OTP cannot create identity',async()=>{
  const {identity,database,sent}=await setup();
  await identity.sendCode({email:'wrong@example.test'});
  const otp=codeFrom(sent),wrong=otp==='000000'?'111111':'000000';
  for(let i=0;i<6;i++)await assert.rejects(identity.register({email:'wrong@example.test',email_code:wrong,password:'Password123'}));
  await assert.rejects(identity.register({email:'wrong@example.test',email_code:otp,password:'Password123'}));
  assert.equal(database.prepare('SELECT count(*) n FROM auth_user').get().n,0);
  await identity.sendCode({email:'expired@example.test'});
  database.prepare('UPDATE auth_verification SET expiresAt=?').run(Date.now()-3600000);
  await assert.rejects(identity.register({email:'expired@example.test',email_code:sent[1].text.match(/\b\d{6}\b/)[0],password:'Password123'}));
  database.close();
});

test('send throttling, failure propagation and legacy account registration guard',async()=>{
  const {identity,database,sent}=await setup();
  await identity.sendCode({email:'a@example.test'});
  await assert.rejects(identity.sendCode({email:'a@example.test'}),e=>e.status===429);
  assert.equal(sent.length,1);
  database.close();
  const legacy=await setup({legacyExists:async()=>true});
  await assert.rejects(legacy.identity.sendCode({email:'old@example.test'}),e=>e.status===409);
  assert.equal(legacy.sent.length,0);legacy.database.close();
  const failed=await setup({fetcher:async()=>new Response('{}',{status:403})});
  await assert.rejects(failed.identity.sendCode({email:'new@example.test'}));
  assert.equal(failed.database.prepare('SELECT count(*) n FROM auth_user').get().n,0);failed.database.close();
});

test('Turnstile fails closed and checks hostname/action, disposable domain policy',async()=>{
  const env={BETTER_AUTH_URL:'http://localhost:8000',BETTER_AUTH_SECRET:'test-secret-at-least-32-characters-long-123',TURNSTILE_ENABLED:'1',TURNSTILE_SITE_KEY:'test-site',TURNSTILE_SECRET_KEY:'test-secret'};
  const {identity,database}=await setup({env,fetcher:async()=>new Response(JSON.stringify({success:true,hostname:'attacker.test',action:'register_email'}))});
  await assert.rejects(identity.sendCode({email:'a@example.test'}),e=>e.status===403);
  await assert.rejects(identity.sendCode({email:'a@example.test',turnstile_token:'fake'}),e=>e.status===403);
  database.close();
  const blocked=await setup({env:{...env,TURNSTILE_ENABLED:'0',AUTH_BLOCKED_EMAIL_DOMAINS:'disposable.test'}});
  await assert.rejects(blocked.identity.sendCode({email:'a@sub.disposable.test'}),e=>e.status===422);
  blocked.database.close();
});

test('legacy Python PBKDF2 hashes remain valid, wrong password and malformed hashes fail',async()=>{
  const salt=Buffer.from('00112233445566778899aabbccddeeff','hex');
  const hash=`pbkdf2_sha256$260000$${salt.toString('hex')}$${pbkdf2Sync('legacy-password',salt,260000,32,'sha256').toString('hex')}`;
  assert.equal(await verifyCompatiblePassword({password:'legacy-password',hash}),true);
  assert.equal(await verifyCompatiblePassword({password:'wrong',hash}),false);
  assert.equal(await verifyCompatiblePassword({password:'wrong',hash:'pbkdf2_sha256$9999999999$x$x'}),false);
  const {identity,database}=await setup();
  const now=Date.now();
  database.prepare('INSERT INTO auth_user(id,name,email,emailVerified,createdAt,updatedAt) VALUES(?,?,?,?,?,?)').run('legacy-user','旧账号','old@example.test',0,now,now);
  database.prepare('INSERT INTO auth_account(id,accountId,providerId,userId,password,createdAt,updatedAt) VALUES(?,?,?,?,?,?,?)').run('credential','legacy-user','credential','legacy-user',hash,now,now);
  const result=await identity.login({email:'old@example.test',password:'legacy-password'});
  assert.equal(result.user.id,'legacy-user');assert.equal(result.user.emailVerified,false);
  database.close();
});

test('backup link uses the same one-time OTP, requires password and cannot switch email',async()=>{
  const {identity,database,sent,redis}=await setup();
  await identity.sendCode({email:'link@example.test'});
  const token=sent[0].text.match(/#register=([a-f0-9]{64})/)[1];
  assert.equal((await identity.linkInfo({registration_token:token})).email,'link@example.test');
  assert.ok([...redis.values.values()].every(v=>!v.includes(codeFrom(sent))));
  await assert.rejects(identity.register({email:'other@example.test',registration_token:token,password:'Password123'}),e=>e.status===403);
  await assert.rejects(identity.register({email:'link@example.test',registration_token:token,password:'short'}),e=>e.status===422);
  const result=await identity.register({email:'link@example.test',registration_token:token,password:'Password123'});
  assert.equal(result.user.emailVerified,true);
  await assert.rejects(identity.linkInfo({registration_token:token}),e=>e.status===403);
  await assert.rejects(identity.register({email:'link@example.test',email_code:codeFrom(sent),password:'Password123'}));
  database.close();
});

test('Redis email lock serializes concurrent submissions and duplicate mail sends',async()=>{
  const {identity,database,sent}=await setup();
  const results=await Promise.allSettled([identity.sendCode({email:'parallel@example.test'}),identity.sendCode({email:'parallel@example.test'})]);
  assert.equal(results.filter(r=>r.status==='fulfilled').length,1);assert.equal(sent.length,1);
  const body={email:'parallel@example.test',email_code:codeFrom(sent),password:'Password123'};
  const registered=await Promise.allSettled([identity.register(body),identity.register(body)]);
  assert.equal(registered.filter(r=>r.status==='fulfilled').length,1);
  assert.equal(database.prepare('SELECT count(*) n FROM auth_user').get().n,1);
  database.close();
});
