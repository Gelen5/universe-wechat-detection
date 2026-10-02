# Release Candidate Report

Updated: 2026-10-02

## Verdict

**NOT READY FOR PRODUCTION**

The application stack is healthy, but the funded text-provider account ran out
of credit during the latest concurrent two-user workflow probe. The final
content-completion gate therefore still cannot pass.

## Latest live recheck (2026-10-02)

- Candidate: `a7c4186`; local suite: `203 passed, 9 subtests passed`.
- The public WeChat conversation path completed article, image, review and
  typeset; its final HTML included a generated image between body paragraphs,
  and the trial wallet changed `30 -> 0` across three charged runs.
- Two concurrent Native Skill users completed with SSE replay, saved artifacts,
  one debit each (`30 -> 20`) and cross-user `404` responses.
- The durable auto/interactive workflow probe queued both tasks while the
  worker was stopped, reconnected SSE, resumed all three interactive decisions,
  and denied cross-user snapshot/event access (`404`).
- The same probe did **not** complete: the provider returned insufficient
  credit and a precharge failure during later nodes. Both workflows failed and
  their trial wallets were refunded to `30 -> 30`. Completion events and final
  debit checks consequently failed. The probe ended with `RC_EXIT=1`; Web and
  Worker were restored and the public readiness endpoint returned `200`.
- Earlier in this recheck, review exposed a nonliteral issue quote and a
  300-second node timeout. The candidate now reanchors review quotes to exact
  article spans and enforces a 1200/1260-second node budget. Interactive mode
  advanced past review to delivery; automatic mode exhausted credit at review.
  Neither two-user completion nor sustained provider capacity is proven.

The previous September 21 snapshot below is retained as historical context.

## Candidate

- Release: `b9f57a433ff864c0edfbd3fe1c6d3f5779656931`
- Alembic: `20260921_0007 (head)`
- Local suite: `168/168 passed`
- Services: PostgreSQL healthy, Redis healthy, Web healthy, Worker healthy,
  Beat running, migration exited `0`
- Workflow node budget: 300-second soft timeout, 330-second hard timeout,
  two transient retries

## Live checks that passed

- Two users submitted workflows concurrently while the Worker was stopped.
- Both workflows remained durably queued and resumed after Worker recovery.
- Web restart did not lose workflow state.
- SSE reconnected with persisted monotonic event ids.
- Interactive mode reached `waiting_user`; a versioned decision resumed it.
- Cross-user workflow snapshot and event access returned `404`.
- Failed workflows left both test wallets unchanged at `30 -> 30`.
- PostgreSQL migrations can be run repeatedly without changing the current head.

## Blocking check

The final automatic and interactive workflows failed when the provider returned
`用户额度不足`. Both stopped at the strategy stage before article delivery.
This is an external account-credit failure, not an application wallet failure.

Public TLS is now configured for the root and `www` domains. HTTP redirects to
HTTPS, both HTTPS workbench routes return `200`, the HTTPS readiness endpoint
returns `200`, and the Certbot renewal dry-run succeeds.

Earlier RC attempts also showed that the previous configured model alias was no
longer available and that long requests on another model had unstable upstream
connections. The current provider model is `kimi-k2.5`; model identifiers remain
server-side and are not exposed to ordinary users.

## Required recheck

1. Ensure the configured provider account has sufficient credit for two
   concurrent, complete article workflows; a partial top-up was not enough.
2. Run `scripts/release_candidate_probe.py` against the production Compose stack.
3. Require both automatic and interactive workflows to complete with articles,
   all three interactive decisions to resume, SSE completion events to replay,
   both wallets to debit exactly once, and cross-user access to remain denied.
4. Only then change the verdict to `READY FOR PRODUCTION`.
