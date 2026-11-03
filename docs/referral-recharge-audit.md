# Recharge referral audit — 2026-11-03

Audited main: `d9f45dbfbd0c9dc40232c14bb0938803e5e9a057`.
Isolated branch: `feat/referral-recharge-20261103`.
Initial audit below is historical. See final delivery status immediately below.

## Final delivery status — 2026-11-03

Implemented: old registration/first-task rewards removed, relationships and historical balances preserved, new registration trial unchanged. Verified Alipay payment facts feed order-unique rewards; integer cents calculation uses 10% first charge, 5% repeat within fixed 90 days, 10 points/yuan and gross lifetime cap 100 per friend. Only bonus receives rewards. Historical first payment dates remain authoritative; missing provenance enters manual review. No retrospective campaign awards.

Flow: invite registration → bind only → signed Alipay notice/authenticated query → actual amount/time/trade fact → original purchase credit → eligibility and risk checks → inviter wallet database row lock → unique order reward + bonus ledger in one transaction. Refund reservation → platform success → cumulative refund event → bonus-only reversal → recorded debt if insufficient → future reward offset. Durable facts and periodic reconciliation recover interrupted settlement.

Additive tables: referral_campaign, referral_recharge_rewards, referral_verified_payments, referral_verified_refunds, referral_refund_requests, referral_recharge_reviews and referral_reward_risks. PostgreSQL row locks and SQLite BEGIN IMMEDIATE serialize financial changes. No history deletion, wallet rebuild or destructive cleanup. Migration: db/alembic/versions/20261103_0012_referral_recharge.py; startup additive schema matches current production approach. Do not blindly upgrade unrelated historical migrations.

Changed components: server/referrals.py, accounts.py, referral_reward_rules.py, referral_recharge.py, alipay_pay.py, main.py, invite_page.py, wallet_page.py, static/app.js, static/index.html and related tests/migration. accounts task settlement callers no longer invoke old activation. Legacy compatibility on_usage_completed is a no-op; legacy rewarded status does not gate new awards.

Validation: 69 related local tests passed (rules, registration, RSA signature/tamper, notification replay, refunds, bonus debt, permissions, 320/390/1440 UI). Independent PostgreSQL schema-only temporary database passed 20 integration tests including concurrent order/cap cases. No production customer data copied. Broader legacy tests still reference retired WORKBENCH_EXECUTOR (two failures reproduced on clean main) and workbench tab selectors (two browser failures); they were not deleted or skipped. No production real-money payment/refund acceptance performed.

Preview: D:/Download/workbench-audit-20261027/referral-recharge-20261103/invite-390.png (synthetic demo values).

Rollout: production backup /opt/universe-data/backups/pre-referral-recharge-20261103.dump already created with restricted permissions. Preflight legacy referral count, old referral ledger count and invited historical paid orders were all zero. Publish committed SHA using /opt/universe-deploy/deploy.sh. Startup adds tables; then authenticated administrator POST /api/admin/referral-recharge/campaign with enabled=true. It only enables against production payment gateway and persists the initial UTC effective time, never resetting on restart. No user refund entrance; existing refund APIs now require administrator. Admin page /admin/referral-recharge provides stats, ledger queries, risk approval, reconciliation and querying platform-confirmed refund results by order/request ID. Invite and wallet use server rules and masked friends.

Operations: monitor referral exception logs, pending review/refund records and reversal debt; reconcile platform payments/refunds against unique reward rows and bonus transactions. Pause with the same campaign API enabled=false. Keep new code and immutable financial history; prefer forward fixes. Never roll back to old reward-paying code or restore a database over subsequent live payments. Fixed campaign start prevents old-order backfill. Missing history or externally notified refunds without sufficient proof remain visible for review, not silently treated as first recharge.

## Historical initial audit (superseded by final status above)

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
