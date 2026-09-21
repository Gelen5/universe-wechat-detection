# Architecture Audit

Updated: 2026-09-21

## Scope and migration rule

This is an incremental migration of the existing creator workbench. Working
authentication, accounts, admin, wallet, legacy creator APIs and business rules
remain available. The normalized Conversation path is the target architecture;
legacy endpoints are compatibility adapters until the new client covers their
user journeys.

## Current architecture

- FastAPI serves authentication, admin, billing, legacy creator/workflow APIs,
  and the normalized Conversation, Run, Artifact and SSE APIs.
- PostgreSQL is the production source of truth. SQLAlchemy models and Alembic
  migrations own durable workflow and conversation state. SQLite remains a
  local/test compatibility option.
- Redis is the Celery broker/result backend and an SSE wake-up channel. It is
  not the source of truth for runs or artifacts.
- Celery executes normalized Agent Runs and the legacy durable workflow. Beat
  recovers stale leases after worker loss.
- Skill manifests are discovered under `vendor/skills`; the selected Skill's
  instructions and allowlisted tools are loaded only after routing.
- Model calls go through `ModelService` and provider interfaces. Artifact files
  go through `StorageProvider` with local and S3-compatible implementations.

## Reused working capabilities

- `server/accounts.py`: login, users, admin, wallet, ledger and legacy usage.
- `server/creator_tools.py`, `server/skill_runtime.py`, and the existing Skills:
  domain operations reused as allowlisted Agent tools.
- `server/workflow_*`: durable legacy workflow, decisions, retries and SSE.
- Existing static workbench and old APIs remain operational during migration.
- Existing API settings and text/image provider separation remain server-side.

## Target path now present

- Core models: Conversation, Message, Run, ToolCall, Artifact, ProviderCall,
  RunEvent, Usage and Billing attribution.
- Skill Registry: manifest schema, discovery, validation and runtime loading.
- Agent: context, manual/auto router, bounded native tool loop and orchestrator.
- Async execution: PostgreSQL Run -> Celery -> Worker with leases and recovery.
- APIs: asynchronous message submission, run status/cancel, history, artifact
  versions/files and replayable SSE with `Last-Event-ID`.
- Billing: atomic reservation, settlement/refund and per-run provider usage.
- Browser: the公众号 creation surface now uses Conversation/Run/SSE/Artifact
  APIs directly, restores persisted runs after refresh, and creates immutable
  Artifact revisions when users edit the current work.
- Tool outputs create typed, idempotent Artifacts. Generated image payloads are
  validated and copied into owner-scoped object storage instead of persisting
  provider base64 or relying only on temporary provider URLs.

## Legacy paths still in service

- `/api/creator/chat` and per-feature creator endpoints.
- `/api/workflows/*` and the current browser workflow client.
- `ThreadPoolExecutor` in legacy job handling only; normalized Agent Runs use Celery.
- Legacy conversation snapshots embedded in workflow/session JSON.

These paths must not be deleted until their UI and API consumers use the
normalized Conversation service and regression tests prove parity.

## Duplication and technical debt

- Two conversation models currently coexist: normalized database messages and
  legacy session JSON.
- Two event clients coexist: normalized Run SSE and legacy Workflow SSE.
- Legacy billing and normalized Run billing share tables but use separate
  service functions.
- Some legacy tools call provider adapters directly; new Agent calls use
  `ModelService`.
- `server/main.py` remains large because compatibility routes have not yet been
  split into routers.
- Legacy feature tabs still use their compatibility clients; the公众号 surface
  is the first migrated Chat + Artifact workspace.

## Ten principal production risks

1. The current commit still needs a fresh Docker release-candidate run against
   PostgreSQL, Redis and a real Celery worker; Docker is unavailable on this host.
2. Legacy thread-pool jobs remain process-local compatibility paths.
3. Queue taxonomy is only partially separated (`creator` and `chat`); Tool
   execution is not yet split into text/image/external worker pools.
4. Some legacy card-image tools still call compatibility provider adapters
   before their results enter normalized Artifact storage.
5. Provider-side idempotency depends on the configured vendor honoring the
   stable `Idempotency-Key` header.
6. Auto routing still needs live-provider ambiguity and quality evaluation.
7. The normalized browser does not yet expose a recent-conversation list.
8. Normalized publishing is not implemented; publishing remains on the legacy
   confirmed workflow path.
9. `render.yaml` describes only the historical single Web service and is not a
   production replacement for the Compose Web/Worker/Redis/PostgreSQL stack.
10. Production object storage credentials and bucket lifecycle policy require
    deployment configuration and operational verification.

## Migration plan

1. Keep old routes stable while all new work uses normalized core services.
2. Finish the ChatGPT-style client against Conversation/Run/SSE/Artifact APIs.
3. Route old creator endpoints into the same services, one Skill at a time.
4. Add distributed rate limiting, structured logs, metrics and security gates.
5. Run PostgreSQL/Redis/Celery restart and multi-user release-candidate tests.
6. Mark legacy executors deprecated, observe production, then remove them in a
   later compatibility release.

## Database migration risk

- Existing account and wallet tables are reused; migrations are additive.
- No migration drops or recreates production tables.
- Run billing uses wallet row locks and unique idempotency keys on PostgreSQL.
- SQLite cannot prove row-lock behavior; PostgreSQL concurrency tests remain a
  mandatory release gate.

## Verification baseline

- The test suite contains unit/integration coverage for registry, providers,
  Agent orchestration, Celery run handling, SSE replay, artifacts, storage,
  billing, workflow recovery and authorization.
- At this audit update, the complete local suite passes 167 tests, including an
  API -> Celery task -> native ToolCall -> Artifact -> Assistant Message chain.
- Fresh SQLite migration reaches `20260921_0007`; Web startup and the normalized
  workbench/static asset checks pass locally.
- Completion is not claimed until the new browser E2E and production release
  checks pass against PostgreSQL, Redis and Celery.
