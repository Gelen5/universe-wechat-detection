from datetime import datetime, timedelta, timezone
import pytest
from server.referral_reward_rules import amount_cents, reward, reversal

T = datetime(2026, 11, 3, tzinfo=timezone.utc)

@pytest.mark.parametrize('cents,expected', [(1000,10),(5000,50),(10000,100),(999,9),(1,0)])
def test_first(cents, expected):
    assert reward(cents=cents, first_payment=T, paid_at=T, effective_at=T,
                  is_first=True, lifetime_granted=0)[2] == expected

def test_repeat_window_and_history():
    args=dict(cents=5000, first_payment=T, effective_at=T,
              is_first=False, lifetime_granted=50)
    assert reward(**args, paid_at=T+timedelta(days=1))[2] == 25
    assert reward(**args, paid_at=T+timedelta(days=90))[2] == 0
    assert reward(**args, paid_at=T-timedelta(seconds=1))[2] == 0
    assert reward(**dict(args,lifetime_granted=100),paid_at=T+timedelta(days=1))[2] == 0

def test_historical_first_not_reset():
    assert reward(cents=1000,first_payment=T-timedelta(days=100),paid_at=T,
                  effective_at=T,is_first=False,lifetime_granted=0)[2] == 0

def test_partial_refunds_are_cumulative_and_keep_cap():
    args=dict(paid_cents=1000,original_grant=10,rate_bps=1000,points_per_yuan=10)
    first=reversal(**args,refunded_cents=1,already_reversed=0)
    assert first==1
    assert reversal(**args,refunded_cents=1,already_reversed=first)==0
    assert reversal(**args,refunded_cents=1000,already_reversed=first)==9

@pytest.mark.parametrize('value',[1.1,'NaN','Infinity','-1','1.001'])
def test_invalid_money(value):
    with pytest.raises(ValueError): amount_cents(value)

def test_exact_money():
    assert amount_cents('99.90')==9990
