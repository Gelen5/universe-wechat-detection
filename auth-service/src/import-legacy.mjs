export async function importLegacyAccounts(pool, email = null) {
  const client=await pool.connect();
  try {
    await client.query('BEGIN');
    // Serialise imports across startup and first-logins on multiple instances.
    await client.query("SELECT pg_advisory_xact_lock(hashtext('universe-better-auth-import'))");
    const collision=await client.query('SELECT 1 FROM users u JOIN auth_user a ON lower(a.email)=lower(u.email) WHERE a.id<>u.id LIMIT 1');
    if(collision.rowCount)throw Error('Identity ID collision: manual reconciliation required');
    const filter=email ? ' WHERE lower(email)=$1' : '';
    const args=email ? [email] : [];
    await client.query(`INSERT INTO auth_user (id,name,email,"emailVerified","createdAt","updatedAt")
      SELECT id,display_name,lower(email),false,created_at::timestamptz,now() FROM users${filter}
      ON CONFLICT(id) DO NOTHING`,args);
    await client.query(`INSERT INTO auth_account (id,"accountId","providerId","userId",password,"createdAt","updatedAt")
      SELECT 'legacy-'||u.id,u.id,'credential',u.id,u.password_hash,u.created_at::timestamptz,now()
      FROM users u WHERE NOT EXISTS(SELECT 1 FROM auth_account a WHERE a."userId"=u.id AND a."providerId"='credential')
      ${email ? 'AND lower(u.email)=$1' : ''}`,args);
    await client.query('COMMIT');
  } catch(error) {await client.query('ROLLBACK');throw error;}
  finally {client.release();}
}
