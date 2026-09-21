# Release Candidate Report

Updated: 2026-09-21

## Verdict

**NOT READY FOR PRODUCTION**

The application stack is healthy, but the configured text-provider account is
out of credit and the public domain does not complete an HTTPS handshake. The
final production gate therefore cannot pass.

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

The public HTTP health and `/workbench` routes return `200`, but both equivalent
HTTPS requests fail during TLS setup. A valid certificate and HTTPS reverse-
proxy listener remain mandatory before production release.

Earlier RC attempts also showed that the previous configured model alias was no
longer available and that long requests on another model had unstable upstream
connections. The current provider model is `kimi-k2.5`; model identifiers remain
server-side and are not exposed to ordinary users.

## Required recheck

1. Fund the configured provider account or replace it with a funded compatible
   text provider.
2. Install and verify a valid TLS certificate for the public domain.
3. Run `scripts/release_candidate_probe.py` against the production Compose stack.
4. Require both automatic and interactive workflows to complete with articles,
   all three interactive decisions to resume, SSE completion events to replay,
   both wallets to debit exactly once, and cross-user access to remain denied.
5. Only then change the verdict to `READY FOR PRODUCTION`.
