# Easel integration audit

Date: 2026-09-30. Upstream inspected at `ZJU-REAL/Easel` commit
`4b9c03cf2129b6155595b66fc1e604546a3aa4ad`.

## 1. Current system

Universe is the public FastAPI system. PostgreSQL owns conversations, runs,
tool calls, events and artifacts; Redis transports Celery jobs and wakes SSE;
the account service owns authentication and the wallet. `server/agent` routes
and executes allowlisted manifests in `vendor/skills`; `server/storage` owns
local or S3-compatible blobs. The compatibility creator and workflow APIs
remain in use. Easel must enter behind this existing execution and billing
path, never as a second public application.

## 2. Easel architecture

Easel's CLI (`easel/cli.py`) exposes `skill`, `doctor`, `ping`, `gateway`,
`chat` and `web`. `easel/commands/skill.py` resolves a Skill directory and
invokes `openclaw --profile easel agent ...` in a subprocess. Its Web app
(`web/app.py`) owns separate sessions, profile files, output files, platform
login state and publishing APIs. The bundled Skill tree contains Python,
Node, browser and media executables. Its OpenClaw workspace location varies
by installed OpenClaw version (`easel/openclaw_workspace.py`).

## 3. Directly reusable modules

Use Easel's pinned Skill instructions, metadata, discovery/plan/produce
logic, CLI diagnostics and individual safe scripts within a separate runtime.
Retain Universe's login, wallet, Run, ToolCall, SSE, Artifact and storage code.

## 4. Modules needing an adapter

Skill invocation, progress/events, Profile materialization, attachments,
output ingestion, account credentials, cancellation and usage reporting require
explicit typed contracts. Easel's CLI printout and exit code alone do not
constitute a durable, billable artifact or an idempotent execution result.

## 5. Modules that must not be copied into the public Web

Do not mount Easel's `web/app.py` or expose port 7860. Do not run its CLI or
OpenClaw Gateway in the FastAPI Web process. Do not import its global profile,
output or browser-session layout as SaaS storage. Do not register every
upstream Skill as a trusted in-process tool.

## 6. Data model difference

Universe uses owner-scoped PostgreSQL rows and a wallet ledger. Easel uses
local profile and output trees plus its own Web state. PostgreSQL must stay
the source of truth; a runtime workspace is disposable. Runtime execution IDs
must map to one Universe Run/ToolCall and preserve the existing reservation,
settlement and refund sequence.

## 7. Profile difference

Easel's `profiles/<name>/` six-file template is a single-machine identity.
Universe currently has no `creator_profiles` model. Phase 3 needs owner-scoped
rows with optimistic versions, and per-execution materialization into an
unpredictable workspace. A user's display name must never become a path.

## 8. Artifact difference

Easel writes to `outputs/`; Universe has typed `artifacts` with versions and
StorageProvider keys. Current Universe types are limited to article, outline,
topic, image, report, html and markdown (`server/models.py`). Phase 4 must
expand types with a migration, validate file size/MIME and path containment,
ingest to owner-scoped storage, create revisions, then clean the workspace.
The runtime must not return arbitrary host paths or permanent public URLs.

## 9. Skill difference

Universe manifests are trusted only after local validation. Easel has many
OpenClaw Skills, including publish and arbitrary file/shell operations.
Discovery must produce namespaced metadata (`easel:<id>`) and a default-deny
allowlist; execution must remain inside the runtime with risk policy and a
human checkpoint for publishing.

## 10. Publishing difference

Easel's WeChat path can drive an administrator browser session and create a
draft; other platform publishers also use browser state. Universe's confirmed
legacy publishing path already exists. Treat all Easel publishing as a side
effect: preflight, preview, owner confirmation, account-scoped serialization,
remote verification and recorded result. A worker retry may not blindly
repeat a publish click.

## 11. Browser-session risk

The upstream WeChat integration documents browser state under a home-directory
profile (`~/.easel-browser-profiles/WeixinMpProfile`). That location would be
shared across users in a container. A SaaS adapter must supply isolated
per-social-account state, encrypt it at rest, materialize only for one job,
and destroy the temporary browser context after use.

## 12. OpenClaw concurrency risk

The CLI uses the fixed OpenClaw profile `easel` and agent `main`; it generates
a time-based session key. Upstream Web uses session locks, but those do not
separate users sharing an Agent home/workspace. An internal HTTP wrapper alone
does not fix this. Phase 1 must not claim multi-tenant readiness until every
execution gets an isolated OpenClaw state/workspace and bounded concurrency,
or execution is restricted to a demonstrably safe stateless capability.

## 13. License risk

Easel root `LICENSE` is Apache-2.0. Its vendored `gzh-design` has its own
AGPL-3.0 license, confirmed in `skills/openclaw/gzh-design/LICENSE`; the
upstream acknowledgments list other derived/vendor components with licensing
still to verify. Keep `gzh-design` and all unreviewed Skills disabled by
default. A separate per-Skill license inventory is required before enabling
them for commercial SaaS.

## 14. Migration risk

Do not replace existing account, conversation, workflow or artifact tables.
Add additive Alembic migrations and owner-scoped foreign keys. Existing SQLite
test compatibility matters. Web and Worker versions must agree on the
execution contract during rolling deployment.

## 15. Deployment risk

The current Compose publishes only Universe Web on loopback and runs one
Worker pool. Easel needs a pinned build, private Docker network, service
credential, real readiness checks for OpenClaw/Gateway/FFmpeg/Chromium/registry,
resource limits and separate queue capacity. Neither 7860 nor the Gateway
port may be published. Large outputs cannot travel in JSON or database blobs.

## 16. Rollback

Keep `EASEL_ENABLED=0` by default. Disable routing first, let in-flight jobs
settle or fail/refund idempotently, stop the runtime, and retain existing
Universe routes and schema. Do not drop additive tables on rollback. Preserve
Artifact objects and Run history for readback. Revert the Compose/runtime
release independently of the public Web release.

## Phase gates

- Phase 1: pinned, isolated runtime; real doctor/ping/Skill list and one
  side-effect-free execution; original test suite green.
- Phase 2: typed adapter with failure, timeout, cancellation, idempotency,
  artifact and discovery tests. Runtime internals stay invisible above it.
- Phase 3: PostgreSQL Profile is the only durable identity; concurrent users
  with identical display names cannot share a workspace.
- Phase 4: all files survive runtime/Worker replacement in owner-scoped
  Artifact storage; unsafe paths and media are rejected.

This document is an audit, not evidence that any Easel runtime has passed its
acceptance gate.
