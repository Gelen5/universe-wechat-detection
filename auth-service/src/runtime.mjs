import { Pool } from 'pg';
import { createClient } from 'redis';
import { createIdentity } from './identity.mjs';
import { importLegacyAccounts } from './import-legacy.mjs';

export async function runtime(env = process.env) {
  for (const key of ['AUTH_DATABASE_URL','REDIS_URL','BETTER_AUTH_URL','BETTER_AUTH_SECRET','AUTH_BRIDGE_SECRET'])
    if (!env[key]) throw Error(`Missing ${key}`);
  if (env.BETTER_AUTH_SECRET.length < 32 || env.AUTH_BRIDGE_SECRET.length < 32)
    throw Error('Authentication secrets must contain at least 32 characters');
  const pool = new Pool({connectionString:env.AUTH_DATABASE_URL, max:5});
  const redis = createClient({url:env.REDIS_URL});
  redis.on('error', () => console.error('identity.redis.unavailable'));
  await redis.connect();
  const identity = createIdentity({database:pool,redis,env,
    syncLegacy:email=>importLegacyAccounts(pool,email),
    legacyExists:async email => (await pool.query('SELECT 1 FROM users WHERE lower(email)=$1 LIMIT 1',[email])).rowCount > 0});
  return {pool,redis,identity};
}
