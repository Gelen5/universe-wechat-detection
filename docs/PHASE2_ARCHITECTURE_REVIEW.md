# Phase 2 Architecture Review

## Baseline

Phase 1 already provides durable Conversation, Message, Run, ToolCall,
Artifact, ProviderCall and Usage records; PostgreSQL migrations; Redis-backed
Celery execution; replayable SSE; wallet reservation/refund; provider and
storage abstractions; and authenticated owner-scoped APIs.

The normalized path is `Conversation API -> Agent Run -> Skill Router ->
manifest adapter -> ToolCall -> Artifact -> assistant message`. Legacy
`/api/creator/chat`, `/api/workflows/*`, old workbench jobs and their browser
clients remain compatibility paths and must not be removed in Phase 2.

## Findings Before Phase 2.1

### P0 correctness

1. `agent/runtime.py` selected executors with Skill-ID branches.
2. `agent/router.py` owned product-specific keywords.
3. `agent/orchestrator.py` inferred Artifact types from tool names.
4. Auto routing permanently wrote the first Skill onto the Conversation.
5. Provider and Tool idempotency depended on Run or provider ToolCall IDs,
   rather than stable logical steps and canonical arguments.
6. Tools had no common context/result contract, making cancellation, usage,
   storage and future side-effect confirmation inconsistent.

### P1 product and operations

1. Context still needs an explicit budget, summary and active Artifact.
2. Artifact lineage and working copies need schema migrations.
3. Auto billing needs post-route reconciliation and per-tool pricing.
4. Provider streaming and aggregated assistant deltas are not implemented.
5. `app.js` and `conversation-workbench.js` overlap on the workspace surface.
6. Production object storage and queue separation still need operational
   configuration even though their interfaces already exist.

## Phase 2.1 Result

- `ToolContext`, `ToolResult` and `ArtifactOutput` are the execution contract.
- A trusted, Skill-local `runtime.adapter` is loaded by `ExecutorRegistry`.
- Untrusted Skills cannot load Python adapters in the main service.
- Manifest routing keywords/examples/priority replace product rules in Router.
- Tool adapters declare Artifact outputs; Orchestrator only persists them.
- Auto mode stores the selected Skill on each Run and leaves Conversation
  unpinned. Manual mode remains pinned.
- Logical model and Tool idempotency keys include step and request hashes.
- Existing six Skills have their own adapters; adding another Skill does not
  require Agent, Router or API Core changes.

## Plugin Acceptance

`tests/test_plugin_architecture.py` creates a Demo Skill at runtime using only:

- `skill.json`
- `SKILL.md`
- `adapter.py`

It proves discovery, manifest routing, execution, Artifact persistence and
Billing settlement. It also hashes `router.py`, `orchestrator.py`,
`agent/runtime.py` and `conversation_api.py` before and after installation and
requires all hashes to remain identical.

## Modified Surface

- Skill execution protocol and registry under `server/skills/`.
- Generic Agent tool loop, router, runtime assembly and Artifact persistence.
- Existing Skill manifests and their local adapters.
- Tests for the new contract and plugin acceptance.

No database migration is required for Phase 2.1. The additive `GET /api/skills`
catalog is the only public API addition. Legacy
APIs remain available. The next backend phase is Tool Loop hardening: JSON
Schema validation with bounded recovery, continuous heartbeat/cancellation,
remaining-time propagation and high-risk side-effect confirmation. The
three-column UI begins only after those correctness gates pass.

## Phase 2.3 P0 Progress

- Tool arguments are validated against the manifest JSON Schema before any
  executor is called.
- Validation errors are returned to the model as structured tool results, with
  at most two correction attempts.
- Model calls receive a stable logical-step and request-hash idempotency key.
- Tool calls use Run, logical step, tool name and canonical argument hash, so a
  provider changing its ToolCall ID after worker retry cannot repeat effects.
- Cancellation and lease heartbeat checks run around model and tool operations.
- Model timeout and `ToolContext.remaining_seconds()` share one Run deadline.
