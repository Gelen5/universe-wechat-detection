// Isolated test-only process. Docker copies src/ only, never this email sink.
import {DatabaseSync} from 'node:sqlite';
import {getMigrations} from 'better-auth/db/migration';
import {createIdentity} from '../src/identity.mjs';
import {buildServer} from '../src/server.mjs';

const database=new DatabaseSync(':memory:');
const values=new Map();
const redis={
  async get(k){return values.get(k);},
  async set(k,v,o={}) {if(o.NX && values.has(k))return null;values.set(k,v);return 'OK';},
  async del(k){values.delete(k);},
  async eval(s,{keys,arguments:a}){if(values.get(keys[0])===a[0])values.delete(keys[0]);},
  async ping(){return 'PONG';},
};
const emails=[];
const env={BETTER_AUTH_URL:'http://testserver',BETTER_AUTH_SECRET:'fixture-secret-at-least-32-characters-long',RESEND_API_KEY:'fixture',RESEND_FROM:'test@example.test'};
const identity=createIdentity({database,redis,legacyExists:async()=>false,env,
  fetcher:async(url,options)=>{emails.push(JSON.parse(options.body));return new Response('{"id":"fixture"}',{status:200});}});
await (await getMigrations(identity.auth.options)).runMigrations();
const server=buildServer({identity,redis,pool:{query:async()=>({})},bridgeSecret:'fixture-bridge-secret-at-least-32-characters'});
// Route email sink through a separate loopback-only test server to avoid
// altering the production private-RPC handler.
const {createServer}=await import('node:http');
const sink=createServer((req,res)=>{res.setHeader('Content-Type','application/json');res.end(JSON.stringify(emails.at(-1)||{}));});
await new Promise(resolve=>sink.listen(0,'127.0.0.1',resolve));
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
console.log('READY '+JSON.stringify({port:server.address().port,sink:sink.address().port}));
