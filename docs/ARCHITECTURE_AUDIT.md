# Architecture Audit

## Scope

This migration preserves the existing login, account, administrator, wallet,
creator UI, HTTP API, and business rules. It replaces only infrastructure that
prevents safe multi-user execution:

- SQLite persistence becomes PostgreSQL persistence.
- The in-process polling/thread worker becomes Redis + Celery.
- Long creator runs become durable node-by-node workflows.
- Browser polling is supplemented by resumable SSE progress events.

This is an incremental migration. Existing routes and response contracts remain
available while the new workflow API is introduced beside them.

## Current System

| Area | Current implementation | Keep | Migration need |
| --- | --- | --- | --- |
| Authentication | Cookie sessions and account helpers in `server/accounts.py` | Yes | Store the same records in PostgreSQL |
| Accounts/admin | Existing services and routes | Yes | Preserve contracts and permissions |
| Wallet | Reserve, settle, refund, immutable transaction rows | Yes | Use row locking and idempotency in PostgreSQL |
| Creator UI/API | Existing workbench pages and routes | Yes | Add workflow/SSE integration only |
| Creator rules | `server/workbench.py` and current Skill integration | Yes | Execute at durable node boundaries |
| Persistence | Direct SQLite SQL and process-local lock | No in production | SQLAlchemy engine and PostgreSQL |
| Jobs | SQLite polling plus `ThreadPoolExecutor` | No | Celery with Redis broker |
| Cancellation | Process-local set | No | Persistent workflow state plus Redis signal |
| Progress | Job polling | Compatibility only | PostgreSQL event log plus SSE |

## Risk Findings

### P0

1. `threading.RLock` and `BEGIN IMMEDIATE` serialize one Python process only;
   they do not protect wallet or workflow state across Web/Worker replicas.
2. Restart recovery currently fails/refunds running work immediately. A durable
   queue must instead retry from the last completed checkpoint.
3. A workbench advance can execute several expensive stages in one job. A crash
   therefore loses stage-level progress and makes safe retry ambiguous.
4. Cancellation is held in memory and is invisible to another process.

### P1

5. Session state is stored as one JSON payload, so concurrent decisions and
   retry history cannot be audited independently.
6. Browser refresh relies on snapshots and cannot replay missed transitions.
7. Wallet correctness depends on SQLite's database-wide writer lock. PostgreSQL
   requires an explicit wallet-row lock and one reservation transaction.
8. The legacy worker polls the database and has process-local lane limits; two
   worker processes can exceed intended provider concurrency.

### P2

9. Startup schema creation mixes deployment concerns with request-serving code.
10. `/health` proves only that Python responds; it does not prove PostgreSQL or
    Redis readiness.
11. Nginx has no dedicated SSE buffering/timeout policy.

## Existing Request And Billing Flow

1. FastAPI middleware resolves the login cookie and loads the account.
2. Billable synchronous routes reserve points before the route handler.
3. The handler calls the provider or creates a legacy job.
4. Successful responses settle Usage; errors refund the original bucket mix.
5. Full workbench creation is a special case: it reserves points, creates a
   `workbench_job`, then submits an in-process future.
6. The workbench stores generated state in `workbench_sessions.payload_json`.

The new workflow path keeps steps 1 and the wallet semantics, but atomically
creates Usage, ledger, reservation, and `workflow_sessions` in PostgreSQL. Each
later node is independently executed by Celery.

## Current Database

Legacy tables preserved during migration are `users`, `wallets`, `sessions`,
`point_transactions`, `usage_records`, `pricing_rules`, `admin_actions`,
`provider_settings`, `workbench_sessions`, `workbench_jobs`, `jobs`, and the
optional `conversation_locks`. New normalized tables are `workflow_sessions`,
`workflow_nodes`, `workflow_decisions`, and `workflow_events`.

## Skill And Deployment

The Web currently resolves the Skill from `WECHAT_PUBLISHER_SKILL_DIR` and uses
its scripts/converter while preserving provider keys on the server. The durable
engine additionally persists the current Skill `ArticleState` after every node.

The current single-host deployment runs FastAPI behind Nginx. The target remains
one inexpensive host, with six internal Compose services: PostgreSQL, Redis,
migration, Web, Worker, and Celery Beat. Only Nginx/Web is reachable publicly.

## Migration Boundaries

### Preserved

- Existing public URLs and UI design.
- Existing account, role, pricing, wallet, and creator business semantics.
- Existing provider settings and API-key ownership rules.
- Existing Skill-derived generation logic and generated artifact formats.
- Existing legacy workbench endpoints during the compatibility window.

### Added beside the legacy path

- `server/database.py`: SQLAlchemy 2 engine/session ownership.
- SQLAlchemy models and Alembic migrations.
- Durable workflow session, node, decision, and event tables.
- Redis/Celery execution and distributed locks.
- `/api/workflows/*` orchestration and SSE endpoints.

### Removed only after cutover evidence

- In-process job polling for creator workflows.
- Startup logic that marks all interrupted workflows failed.
- Process-local cancellation for creator workflows.

## Delivery Gates

1. Existing tests stay green against the compatibility database.
2. Alembic creates a clean PostgreSQL schema from zero.
3. SQLite migration dry-run reports table counts without writing.
4. PostgreSQL migration verifies counts and wallet balances before cutover.
5. Wallet reserve/settle/refund tests prove idempotency under concurrency.
6. Auto and interactive modes use the same workflow engine.
7. SSE reconnect replays events after `Last-Event-ID` without duplicates.
8. Worker restart resumes from the last completed node.
9. Production deployment exposes Web only; PostgreSQL and Redis remain internal.
