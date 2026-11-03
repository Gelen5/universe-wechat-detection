# Recharge referral audit — 2026-11-03

Audited main: `d9f45dbfbd0c9dc40232c14bb0938803e5e9a057`.
Isolated branch: `feat/referral-recharge-20261103`.
No production mutations, migrations or deployment performed.

## Observed implementation

- FastAPI, SQLAlchemy compatibility connection, PostgreSQL production and SQLite local tests.
- `referrals._bind_signup` grants 10 bonus points, rejects bindings at daily/monthly/IP limits.
- `accounts.settle_usage` and `settle_usage_with_points` call `_notify_referral_activation`, which invokes `referrals.on_usage_completed`; that grants 15 inviter and 10 invitee bonus points. Existing tests explicitly assert these legacy rewards.
- `accounts.credit_bucket` creates wallet changes and point transactions using its caller's connection. It is the reusable grant primitive.
- `referrals.init_schema` creates tables and columns at runtime; Alembic also contains a referrals revision. `_ensure_foreign_keys` currently deletes orphan referral records. This destructive cleanup must be removed before any migration is approved.
- Alipay notify validates RSA signature, app ID, seller and order total. A synchronous return only redirects. This is a real payment system, not a front-end success simulation.
- `_credit_recharge` grants purchase points through `accounts.credit_alipay_recharge`, then marks recharge CREDITED using a separate transaction. Rewards cannot be added as an untracked callback after this early-return branch.
- `refund_order` reads refunded total, calls Alipay, then increments refunded amount and changes status in separate operations. It only accepts PAID; repeated partial refunds and concurrent duplicate requests need explicit refund records and locks before rewards can be enabled.
- `_is_paid_notification` duplicate path retries purchase crediting. The new reward operation must remain idempotent on this path too.

## Minimum implementation boundary

1. New additive reward, refund-event and persisted campaign tables. Keep historical referral rows and transactions intact.
2. Replace binding rejections for volume/IP with independent risk flags; keep unique invitee constraint. Shared IP alone must not block reward or registration.
3. Remove old settlement calls and legacy grant behavior together with UI promises. Update historical tests to assert new behavior without dropping coverage.
4. Persist verified payment facts and first-payment history. Missing historical payment time or provenance enters review; never infer first charge from campaign start or referral status.
5. Serialize reward settlement with database row locks (SQLite BEGIN IMMEDIATE; PostgreSQL FOR UPDATE), with unique order reward and transaction request keys. Grant record, bonus ledger and wallet change commit together.
6. Record cumulative verified refunds under unique refund request keys; reverse only bonus, persist uncollected debt, and offset future referral rewards. Cap uses lifetime gross grants so refunds cannot reopen allowance.
7. Idempotent reconciliation handles payment/credit/reward interruption. Campaign disabled by default with explicit fixed UTC start; no historical backfill.
8. Derive invite page, wallet and admin numbers from this new ledger and server rules. Never use legacy rewarded status as eligibility.

## Work completed in this branch

`server/referral_reward_rules.py` supplies pure integer-money rules and strict aware-time handling. It has no payment trigger and no wallet effects. First/repeat rates, exchange ratio, cap and duration are supplied through an immutable rule object. Cumulative refund calculation preserves rounding consistency and grant caps.

`tests/test_referral_reward_rules.py`: 14 passed. These are calculation tests only, not payment integration, concurrency, PostgreSQL or production acceptance.

## Not yet implemented / release blockers

The transactional settlement tables, trusted payment integration, refund idempotency repair, debt ledger, legacy shutdown, risk controls, UI/admin update, migration dry run, PostgreSQL concurrency tests and full acceptance suite remain outstanding. Do not enable or deploy this branch as the new program. Existing live invitation behavior has not been changed by this work.
