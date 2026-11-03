"""Fail-closed staging tests, not complete payment integration acceptance."""
from tests import support  # noqa: F401
from server import accounts, referral_recharge


def test_missing_campaign_cannot_issue_rewards():
    accounts.init_db()
    referral_recharge.init_schema()
    with accounts._connect() as c:
        c.execute('DELETE FROM referral_campaign')
        before=c.execute('SELECT COUNT(*) FROM point_transactions').fetchone()[0]
    assert referral_recharge.settle('unverified-client-order')=='disabled'
    with accounts._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM point_transactions').fetchone()[0]==before


def test_no_automatic_campaign_activation():
    with accounts._connect() as c:c.execute('DELETE FROM referral_campaign')
    referral_recharge.init_schema()
    with accounts._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM referral_campaign').fetchone()[0]==0
