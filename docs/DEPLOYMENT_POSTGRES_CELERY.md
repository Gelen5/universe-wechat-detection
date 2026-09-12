# PostgreSQL, Redis And Celery Deployment

## Preconditions

- Back up `data/creator_accounts.db`, `output/`, and the current `.env`.
- Keep provider keys only in the server `.env`; never commit them.
- Install the current `weChat-autoCreate` checkout at
  `/opt/universe-skills/weChat-autoCreate`.
- Generate a long random `POSTGRES_PASSWORD`.

## First Migration

```bash
cp .env.example .env
# Edit .env before continuing.
docker compose up -d postgres redis
docker compose run --rm migrate
docker compose run --rm migrate sh -lc \
  'python scripts/migrate_sqlite_to_postgres.py --source /legacy/creator_accounts.db --target "$DATABASE_URL" --dry-run'
docker compose run --rm migrate sh -lc \
  'python scripts/migrate_sqlite_to_postgres.py --source /legacy/creator_accounts.db --target "$DATABASE_URL"'
docker compose up -d web worker
```

The copy command is idempotent and verifies row counts plus all wallet bucket
totals. Do not switch traffic when `verified` is not `true`.

## Verification

```bash
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
docker compose ps
docker compose logs --tail=100 web worker
```

Verify login, wallet balance, admin authorization, one interactive workflow,
one automatic workflow, cancel/refund, retry, browser refresh, and SSE replay.

## Rollback

1. Stop public traffic or enable maintenance mode.
2. Stop the new Web/Worker containers.
3. Restore the prior release and its SQLite database backup.
4. Start the prior services and verify `/health` plus login/wallet reads.

Do not merge PostgreSQL writes back into SQLite. A rollback after accepting new
production writes requires a maintenance window and an explicit data export.

## Backup

Run `scripts/backup_production.sh` from a PostgreSQL image or host with
`pg_dump`. Store encrypted copies outside the server and test restore regularly.
