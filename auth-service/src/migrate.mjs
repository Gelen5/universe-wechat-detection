import { getMigrations } from 'better-auth/db/migration';
import { runtime } from './runtime.mjs';
import { importLegacyAccounts } from './import-legacy.mjs';

const {identity,pool,redis} = await runtime();
try {
  const migrations=await getMigrations(identity.auth.options);
  await migrations.runMigrations();
  await importLegacyAccounts(pool);
  console.log('Better Auth schema and legacy credential import complete');
} finally {await redis.quit();await pool.end();}
