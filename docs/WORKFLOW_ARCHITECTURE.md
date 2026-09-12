# Workflow Architecture

## Principle

One durable engine serves both modes. Auto mode automatically supplies allowed
decisions; interactive mode pauses at the same checkpoints for a user decision.
The article pipeline is never duplicated.

## Nodes

| Order | Node | Responsibility | Interactive checkpoint |
| --- | --- | --- | --- |
| 1 | `intent` | Normalize request, audience, mode, constraints | No |
| 2 | `topic` | Produce evidence-bounded topic candidates | Yes |
| 3 | `research` | Collect and normalize supporting material | No |
| 4 | `strategy` | Select angle, structure, and content contract | Yes |
| 5 | `draft` | Generate the editable article draft | No |
| 6 | `review` | Apply review gates and revisions | No |
| 7 | `visual` | Plan/generate image assets and placements | Yes |
| 8 | `delivery` | Render preview/export artifacts; never auto-publish | No |

Each node is a Celery task and a safe checkpoint. A node transition is committed
to PostgreSQL before the next task is enqueued.

## Durable State

`workflow_sessions` owns the workflow identity, user, mode, current state,
version, cancellation flag, and timestamps.

`workflow_nodes` owns one attempt per node, input/output JSON, status, error,
Celery task id, and timing. Its idempotency key prevents duplicate side effects.

`workflow_decisions` stores user or auto decisions independently from generated
content. Decisions use optimistic session versions to reject stale browser tabs.

`workflow_events` is an append-only ordered event stream. PostgreSQL is the
source of truth; Redis Pub/Sub only wakes connected SSE consumers.

## State Machine

Session statuses:

`queued -> running -> awaiting_input -> running -> completed`

Terminal alternatives are `cancelled` and `failed`. A failed node may be retried
without deleting its earlier attempt. Cancellation is cooperative between nodes
and at explicit safe points inside long provider calls.

Node statuses:

`pending -> queued -> running -> completed`

Alternatives are `awaiting_input`, `failed`, `cancelled`, and `invalidated`.

## Auto And Interactive Modes

- Both modes call the same node handlers and persist identical output schemas.
- Auto mode records an explicit `actor=auto` decision and proceeds.
- Interactive mode records `awaiting_input`, emits a checkpoint event, and stops.
- Switching interactive to auto resolves the current checkpoint automatically.
- Switching auto to interactive takes effect at the next checkpoint.
- Editing upstream content increments the session version and invalidates all
  dependent completed nodes before a replacement task is queued.

## Wallet Contract

Reservation and workflow creation occur in one database transaction. PostgreSQL
locks the wallet row with `SELECT FOR UPDATE`. The usage record and immutable
ledger entry share an idempotency key.

- Success settles the reservation once.
- Failure or cancellation refunds the unsettled amount once.
- Celery retries cannot create a second charge or refund.
- Redis locks reduce duplicate work but correctness never depends on Redis.

## SSE Contract

Endpoint: `GET /api/workflows/{workflow_id}/events`

- Auth and workflow ownership are checked before streaming.
- Each frame has the PostgreSQL event id as its SSE `id`.
- `Last-Event-ID` replays all later rows from PostgreSQL.
- After replay, Redis Pub/Sub wakes the stream; the consumer reads PostgreSQL
  again rather than trusting Pub/Sub payloads.
- Heartbeats keep proxies from closing idle streams.
- Slow or disconnected clients never block task execution.

## Failure Recovery

- Celery uses late acknowledgement and rejects work when a worker is lost.
- A retry first reads the durable node attempt and returns its saved result when
  the idempotency key is already complete.
- Web startup does not fail or refund running workflows.
- A recovery scan requeues only stale `queued/running` attempts with no active
  lease; completed nodes are never re-executed.
- Browser refresh fetches the workflow snapshot, then connects with the latest
  event id to close the snapshot/stream race.

## Compatibility Cutover

1. Deploy PostgreSQL/Redis and migrations with legacy routes unchanged.
2. Migrate and verify SQLite data.
3. Enable the new workflow API for internal testing.
4. Point the existing creator page at workflow/SSE APIs behind a feature flag.
5. Verify account, wallet, admin, and creator regressions.
6. Disable legacy creator worker polling only after live workflow evidence.
