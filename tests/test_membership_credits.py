from datetime import timedelta
import pytest
from sqlalchemy import select, update
from server import accounts, database, viral_insights_membership as vim
from tests.test_viral_insights_membership import paywall, clock, _client_for_new_user, _membership_order

@pytest.fixture
def campaign(clock):
    with database.ENGINE.begin() as c:
        old = c.execute(select(vim.credit_campaign.c.started_at)).scalar_one()
        c.execute(update(vim.credit_campaign).values(started_at=(clock['now']-timedelta(days=1)).isoformat()))
    yield
    with database.ENGINE.begin() as c:
        c.execute(update(vim.credit_campaign).values(started_at=old))

def test_year_installments_are_due_and_idempotent(paywall, clock, campaign):
    _, user = _client_for_new_user()
    before = accounts.wallet_summary(user)['bonus']
    oid = _membership_order(user, 'year')
    assert vim.apply_paid(oid)
    assert vim.apply_paid(oid)
    assert accounts.wallet_summary(user)['bonus'] == before + 80
    clock['now'] += timedelta(days=29, hours=23)
    vim.reconcile_credit_grants()
    assert accounts.wallet_summary(user)['bonus'] == before + 80
    clock['now'] += timedelta(hours=1)
    vim.reconcile_credit_grants(); vim.reconcile_credit_grants()
    assert accounts.wallet_summary(user)['bonus'] == before + 160
    with database.ENGINE.connect() as c:
        rows = c.execute(select(vim.credit_grants).where(vim.credit_grants.c.out_trade_no == oid)).mappings().all()
    assert [row['period'] for row in rows] == [0,1]
    clock['now'] += timedelta(days=330)
    vim.reconcile_credit_grants()
    assert accounts.wallet_summary(user)['bonus'] == before + 960
    vim.reconcile_credit_grants()
    assert accounts.wallet_summary(user)['bonus'] == before + 960

def test_refund_preserves_balance_and_stops_future_periods(paywall, clock, campaign):
    _, user = _client_for_new_user()
    oid = _membership_order(user, 'year')
    vim.apply_paid(oid)
    assert accounts.wallet_summary(user)['bonus'] == 80
    assert vim.apply_refund(oid) and not vim.apply_refund(oid)
    assert accounts.wallet_summary(user)['bonus'] == 80
    clock['now'] += timedelta(days=60)
    vim.reconcile_credit_grants()
    assert accounts.wallet_summary(user)['bonus'] == 80
    with database.ENGINE.connect() as c:
        row = c.execute(select(vim.credit_refunds).where(vim.credit_refunds.c.out_trade_no == oid)).mappings().one()
    assert row['granted'] == 80 and row['recovered'] == 0 and row['shortfall'] == 80

def test_refund_never_takes_paid_or_trial_when_bonus_spent(paywall, clock, campaign):
    _, user = _client_for_new_user()
    oid = _membership_order(user, 'week'); vim.apply_paid(oid)
    usage = accounts.reserve_points(user, {'points':30,'feature':'test'}, 'POST', '/test')
    accounts.settle_usage(usage, 200, 1)
    before = accounts.wallet_summary(user)
    assert vim.apply_refund(oid)
    after = accounts.wallet_summary(user)
    assert after['paid'] == before['paid'] and after['trial'] == before['trial']
    with database.ENGINE.connect() as c:
        row = c.execute(select(vim.credit_refunds).where(vim.credit_refunds.c.out_trade_no == oid)).mappings().one()
    assert row['shortfall'] == 30

def test_existing_active_member_gets_one_current_period_only(paywall, clock, campaign):
    _, user = _client_for_new_user()
    oid = _membership_order(user, 'year')
    start = clock['now'] - timedelta(days=75)
    with database.ENGINE.begin() as c:
        c.execute(update(vim.orders).where(vim.orders.c.out_trade_no == oid).values(
            status='PAID', paid_at=start.isoformat(), started_at=start.isoformat(),
            expires_at=(start+timedelta(days=365)).isoformat()))
    vim.reconcile_credit_grants(); vim.reconcile_credit_grants()
    assert accounts.wallet_summary(user)['bonus'] == 80
    with database.ENGINE.connect() as c:
        rows = c.execute(select(vim.credit_grants).where(vim.credit_grants.c.out_trade_no == oid)).mappings().all()
    assert [row['period'] for row in rows] == [2]
    clock['now'] += timedelta(days=15)
    vim.reconcile_credit_grants()
    assert accounts.wallet_summary(user)['bonus'] == 160


def test_callback_and_reconcile_retries_issue_once(paywall, clock, campaign):
    from concurrent.futures import ThreadPoolExecutor
    _, user = _client_for_new_user()
    oid = _membership_order(user, 'month')
    vim.apply_paid(oid)
    def run(i):
        return vim.apply_paid(oid) if i % 2 else vim.reconcile_credit_grants()
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(run, range(10)))
    assert accounts.wallet_summary(user)['bonus'] == 80
    with database.ENGINE.connect() as c:
        rows = c.execute(select(vim.credit_grants).where(vim.credit_grants.c.out_trade_no == oid)).mappings().all()
    assert len(rows) == 1


def test_legacy_expired_member_receives_no_backfill(paywall, clock, campaign):
    _, user = _client_for_new_user()
    oid = _membership_order(user, 'week')
    start = clock['now'] - timedelta(days=20)
    with database.ENGINE.begin() as c:
        c.execute(update(vim.orders).where(vim.orders.c.out_trade_no == oid).values(
            status='PAID', paid_at=start.isoformat(), started_at=start.isoformat(),
            expires_at=(start+timedelta(days=7)).isoformat()))
    vim.reconcile_credit_grants()
    assert accounts.wallet_summary(user)['bonus'] == 0


def test_year_next_period_status_is_reported(paywall, clock, campaign):
    _, user = _client_for_new_user()
    oid = _membership_order(user, 'year')
    vim.apply_paid(oid)
    assert vim._state(user)['credit_next_at'] == (clock['now'] + timedelta(days=30)).isoformat()
    clock['now'] += timedelta(days=30)
    vim.reconcile_credit_grants()
    assert vim._state(user)['credit_next_at'] == (clock['now'] + timedelta(days=30)).isoformat()


def test_simultaneous_first_payment_callback_issues_once(paywall, clock, campaign):
    from concurrent.futures import ThreadPoolExecutor
    _, user = _client_for_new_user()
    oid = _membership_order(user, 'month')
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: vim.apply_paid(oid), range(8)))
    assert all(results)
    assert accounts.wallet_summary(user)['bonus'] == 80
    with database.ENGINE.connect() as c:
        rows = c.execute(select(vim.credit_grants).where(vim.credit_grants.c.out_trade_no == oid)).mappings().all()
    assert len(rows) == 1
