# Production Concurrency Review

Updated: 2026-09-21

## Scope

This review adds no product features. It hardens the existing PostgreSQL, Redis,
Celery, Auto/Interactive workflow, SSE, wallet, and authorization paths for 100
registered users and 20-30 simultaneous creation requests.

## Correctness Invariants

- A user action has one workflow and one usage reservation per idempotency key.
- Wallet debit, usage reservation, workflow creation, and first durable node are
  committed in one PostgreSQL transaction.
- Wallet refund locks the usage and wallet rows; only `reserved -> refunded` can
  create a refund ledger entry.
- A node can only be claimed from `queued`. Completion and failure are fenced by
  Celery task id and node attempt.
- Node completion and the next queued node (or checkpoint/terminal state) commit
  atomically.
- Redis is an optimization lease, not the source of workflow truth. PostgreSQL is
  the durable state and recovery source.
- Every public workflow mutation and SSE stream is scoped to the authenticated
  owner.

## Extreme Scenario Results

| # | Scenario | Result after hardening |
|---|---|---|
| 1 | User clicks Start 10 times | Safe when the client reuses the action idempotency key: one workflow, one debit, nine replays. Verified against PostgreSQL. |
| 2 | Two workers receive one workflow | Safe: PostgreSQL row lock permits only one `queued -> running` claim; duplicate delivery is ignored. |
| 3 | LLM succeeds, worker crashes before DB save | DB remains running and is recovered after the lease timeout. A deterministic provider `Idempotency-Key` is reused. See residual risk below. |
| 4 | Debit succeeds, Celery enqueue fails | Safe: debit, workflow and queued node commit together. Beat redelivers the durable queued row. |
| 5 | Redis restarts during execution | Safe for database correctness: the running PostgreSQL lease blocks a second claim; stale recovery resumes after a crash. Availability may pause briefly. |
| 6 | Server restarts during `waiting_user` | Safe: checkpoint state and expected version are in PostgreSQL; no process-local state is required. |
| 7 | User submits the same decision twice | Safe: owner, checkpoint and optimistic workflow version are checked under row lock; the second submission is rejected. |
| 8 | User cancels while worker runs | Safe: cancellation becomes terminal atomically and active nodes are cancelled. A stale worker is fenced from committing; refund is idempotent. |
| 9 | Worker times out in a node | Safe: soft timeout fails the owned attempt and refunds once; transient transport failures release the lease before bounded retry. |
| 10 | Process crashes while refunding | Safe: conditional usage transition plus wallet row lock prevents double refund. Beat reconciles terminal workflows whose usage is still reserved. Verified with 10 concurrent refund calls. |

## Review Findings And Fixes

### PostgreSQL and wallet

- Added `FOR UPDATE` wallet/usage locking to refund processing.
- Kept charge, ledger, workflow, and initial node in one transaction.
- Added durable terminal billing reconciliation for interrupted settle/refund.

### Celery and workflow execution

- Added task-id and attempt fencing against stale workers.
- Added durable queued-node recovery for broker enqueue loss.
- Added bounded retry lease release and terminal timeout handling.
- Made cancellation terminal immediately and protected all later writes.
- Made node result plus next-node/checkpoint/terminal transition atomic.
- Routed coordination, text, image, external calls and workflow delivery to
  separate Celery queues so worker pools can scale independently.

### Redis, restart, and SSE

- Redis lock contention is an ignored duplicate, not a workflow failure.
- Recovery scans both stale running nodes and queued nodes with missing broker delivery.
- SSE remains backed by PostgreSQL monotonic event ids and supports replay with
  `Last-Event-ID`; Redis only wakes connected streams.

### Authorization

- Snapshot, decision, mode switch, retry, cancel, edit/invalidate, and event replay
  use the authenticated user id. Internal Celery tasks operate only on server-side
  workflow ids and do not expose a public bypass.

## Verification

- Full local suite: `168 passed`.
- Python compile and diff checks: passed.
- PostgreSQL probe: 100 registered users, 30 concurrent creators; passed.
- Ten-click idempotency probe: one workflow, one usage row, one debit; passed.
- Ten-way refund race: one refund ledger entry and restored balance; passed.

## Capacity And Residual Risk

The reviewed design is safe for the stated 100 registered users and 20-30
simultaneous admissions. Provider throughput is still limited by configured Celery
worker concurrency, so requests may queue without violating billing or workflow
correctness.

No distributed system can guarantee exactly-once side effects across an external
LLM HTTP call and a local database transaction. The worker now sends a stable
`Idempotency-Key`; if a configured provider ignores that header, a crash after the
provider response but before the database commit can repeat the provider call.
The database result, charge, refund, and workflow transition remain deduplicated.
Production should prefer providers that document idempotency support.

PostgreSQL and Redis are currently single service instances. This review protects
correctness and restart recovery, but it does not add high availability for a host
or availability-zone failure.

The latest queue and readiness changes still require a fresh Docker release-
candidate run against PostgreSQL, Redis, Web, Worker and Beat before declaring
the current commit ready for production; Docker is unavailable on this host.
