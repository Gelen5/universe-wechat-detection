"""Synthetic payment facts only; never sends money or invokes a real provider."""
import json
import uuid
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from tests import support  # noqa: F401
from server import accounts, referrals, referral_recharge as rr, alipay_pay

T=datetime(2026,11,4,tzinfo=timezone.utc)


class RechargeReferralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        accounts.init_db();referrals.init_schema();alipay_pay.ensure_schema();rr.init_schema()

    def setUp(self):
        self.a=accounts.create_user(uuid.uuid4().hex+'@example.test','testing-pass-123','邀请人')['id']
        self.b=accounts.create_user(uuid.uuid4().hex+'@example.test','testing-pass-123','好友')['id']
        self.code=referrals.ensure_code(self.a)
        self.assertEqual('bound',referrals.bind_signup(self.b,self.code,'shared-network')['status'])
        with accounts._connect() as c:
            c.execute('DELETE FROM referral_campaign')
        rr.configure((T-timedelta(days=1)).isoformat(),True)

    def order(self,cents=1000,when=T,verified=True,status='PAID',credits=None,user=None):
        order=uuid.uuid4().hex;user=user or self.b
        amount=f'{cents//100}.{cents%100:02d}'
        with accounts._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('''INSERT INTO alipay_orders(out_trade_no,app_id,subject,total_amount,status,trade_no,refunded_amount,created_at,paid_at,updated_at)
                VALUES(?,'test-app','synthetic',?,?,?,'0.00',?,?,?)''',(order,amount,status,'trade-'+order,when.isoformat(),when.isoformat(),when.isoformat()))
            c.execute('''INSERT INTO alipay_recharges(out_trade_no,user_id,package_id,credits,amount,status,credited_at,created_at)
                VALUES(?,?,'synthetic',?,?,'CREDITED',?,?)''',(order,user,credits or cents//10,amount,when.isoformat(),when.isoformat()))
            c.execute('COMMIT')
        accounts.credit_alipay_recharge(user,credits or cents//10,order)
        if verified:rr.verified_payment(order,{'out_trade_no':order,'trade_no':'trade-'+order,'buyer_pay_amount':amount,'gmt_payment':when.isoformat()},'verified_signature')
        return order

    def wallet(self,user=None):return accounts.wallet_summary(user or self.a)

    def test_registration_and_tasks_never_grant_invitation_points(self):
        self.assertEqual(0,self.wallet(self.b)['bonus'])
        usage=accounts.reserve_points(self.b,{'points':0,'feature':'test'},'POST','/test')
        accounts.settle_usage(usage,200,1);referrals.on_usage_completed(usage)
        self.assertEqual(0,self.wallet()['bonus'])
        accounts.recharge(self.a,self.b,20,'trial','test grant')
        usage=accounts.reserve_points(self.b,{'points':2,'feature':'test'},'POST','/test')
        accounts.settle_usage_with_points(usage,200,1,2)
        self.assertEqual(0,self.wallet()['bonus'])

    def test_first_10_and_repeat_50_and_cap(self):
        first=self.order();self.assertEqual('settled',rr.settle(first));self.assertEqual(10,self.wallet()['bonus'])
        second=self.order(5000,T+timedelta(days=1));rr.settle(second);self.assertEqual(35,self.wallet()['bonus'])
        third=self.order(100000,T+timedelta(days=2));rr.settle(third);self.assertEqual(100,self.wallet()['bonus'])
        fourth=self.order(5000,T+timedelta(days=3));rr.settle(fourth);self.assertEqual(100,self.wallet()['bonus'])
        self.assertEqual(0,self.wallet()['paid']);self.assertGreater(self.wallet(self.b)['paid'],0)

    def test_first_50(self):
        rr.settle(self.order(5000));self.assertEqual(50,self.wallet()['bonus'])

    def test_window_is_exact(self):
        rr.settle(self.order());rr.settle(self.order(5000,T+timedelta(days=90)))
        self.assertEqual(10,self.wallet()['bonus'])

    def test_paid_state_without_verified_platform_fact_cannot_award(self):
        self.assertEqual('needs_payment_provenance',rr.settle(self.order(verified=False)))
        for status in ['CREATED','CLOSED','PENDING_PAYMENT']:
            self.assertEqual('not_paid',rr.settle(self.order(status=status)))
        self.assertEqual(0,self.wallet()['bonus'])

    def test_repeated_and_concurrent_settlement_is_once(self):
        order=self.order()
        with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(rr.settle,[order]*12))
        self.assertEqual(10,self.wallet()['bonus'])
        with accounts._connect() as c:
            self.assertEqual(1,c.execute('SELECT COUNT(*) FROM point_transactions WHERE request_id=?',('referral-recharge:'+order,)).fetchone()[0])

    def test_multiple_orders_concurrent_cap_is_global_per_friend(self):
        first=self.order(5000);rr.settle(first)
        orders=[self.order(10000,T+timedelta(days=i+1)) for i in range(4)]
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(rr.settle,orders))
        self.assertEqual(100,self.wallet()['bonus'])

    def test_refund_replay_partial_rounding_and_full(self):
        order=self.order();rr.settle(order)
        rr.reserve_refund(order,'part1',1);rr.confirm_refund(order,'part1')
        self.assertEqual(9,self.wallet()['bonus'])
        rr.confirm_refund(order,'part1');self.assertEqual(9,self.wallet()['bonus'])
        rr.reserve_refund(order,'part2',999);rr.confirm_refund(order,'part2')
        self.assertEqual(0,self.wallet()['bonus'])
        self.assertEqual('confirmed',rr.reserve_refund(order,'part2',999))
        with accounts._connect() as c:
            self.assertEqual('10.00',c.execute('SELECT refunded_amount FROM alipay_orders WHERE out_trade_no=?',(order,)).fetchone()[0])

    def test_concurrent_refunds_and_amount_reservations(self):
        order=self.order();rr.settle(order);rr.reserve_refund(order,'same',1000)
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(lambda _:rr.confirm_refund(order,'same'),range(8)))
        self.assertEqual(0,self.wallet()['bonus'])
        with self.assertRaises(ValueError):rr.reserve_refund(order,'new',1)

    def test_spent_reward_does_not_touch_paid_balance_and_offsets_next_reward(self):
        order=self.order();rr.settle(order)
        usage=accounts.reserve_points(self.a,{'points':10,'feature':'test'},'POST','/test')
        accounts.settle_usage(usage,200,1)
        accounts.credit_alipay_recharge(self.a,100,'unrelated-purchase-'+uuid.uuid4().hex)
        rr.reserve_refund(order,'full',1000);rr.confirm_refund(order,'full')
        self.assertEqual(100,self.wallet()['paid']);self.assertEqual(0,self.wallet()['bonus'])
        rr.settle(self.order(5000,T+timedelta(days=1)))
        self.assertEqual(15,self.wallet()['bonus']);self.assertEqual(100,self.wallet()['paid'])
        with accounts._connect() as c:self.assertEqual(0,c.execute('SELECT debt FROM referral_recharge_rewards WHERE order_id=?',(order,)).fetchone()[0])

    def test_historical_rewarded_relationship_is_eligible_and_history_untouched(self):
        with accounts._connect() as c:
            c.execute("UPDATE referrals SET status='rewarded' WHERE invitee_id=?",(self.b,))
            accounts.credit_bucket(c,self.a,15,'bonus',request_id='old-'+uuid.uuid4().hex,source='referral',feature='历史奖励')
        rr.settle(self.order());self.assertEqual(25,self.wallet()['bonus'])

    def test_old_payment_not_first_and_no_backfill(self):
        old=self.order(1000,T-timedelta(days=2));self.assertEqual('ineligible',rr.settle(old))
        rr.settle(self.order(5000));self.assertEqual(25,self.wallet()['bonus'])

    def test_old_first_over_90_days_expires(self):
        self.order(1000,T-timedelta(days=100));rr.settle(self.order(5000))
        self.assertEqual(0,self.wallet()['bonus'])

    def test_unknown_historical_time_fails_closed(self):
        old=self.order(verified=False,when=T-timedelta(days=10))
        self.assertEqual('needs_history_review',rr.settle(self.order(5000)))
        with accounts._connect() as c:self.assertTrue(c.execute('SELECT 1 FROM referral_recharge_reviews WHERE inviter_id=?',(self.a,)).fetchone())

    def test_no_inviter_and_manual_grants_do_not_award(self):
        user=accounts.create_user(uuid.uuid4().hex+'@example.test','testing-pass-123','无邀请')['id']
        self.assertEqual('no_referral',rr.settle(self.order(user=user)))
        accounts.recharge(self.a,self.b,100,'bonus','人工赠分')
        self.assertEqual(0,self.wallet()['bonus'])

    def test_discount_uses_actual_paid_and_no_bonus_base(self):
        order=self.order(5000,credits=999)
        with accounts._connect() as c:c.execute('UPDATE referral_verified_payments SET paid_cents=1000 WHERE order_id=?',(order,))
        rr.settle(order);self.assertEqual(10,self.wallet()['bonus'])

    def test_restart_schema_and_campaign_start_are_stable(self):
        rr.configure((T+timedelta(days=50)).isoformat(),False);rr.init_schema()
        rr.settle(self.order());self.assertEqual(10,self.wallet()['bonus'])

    def test_invalid_evidence_and_refund_reuse_rejected(self):
        order=self.order()
        with self.assertRaises(ValueError):rr.verified_payment(order,{'buyer_pay_amount':'9999','gmt_payment':T.isoformat(),'trade_no':'x'},'test')
        rr.reserve_refund(order,'same',100)
        with self.assertRaises(ValueError):rr.reserve_refund(order,'same',200)

    def test_refund_never_reopens_cap(self):
        order=self.order(10000);rr.settle(order);rr.reserve_refund(order,'full',10000);rr.confirm_refund(order,'full')
        rr.settle(self.order(10000,T+timedelta(days=1)));self.assertEqual(0,self.wallet()['bonus'])

    def test_failure_rolls_back_wallet_and_award_record(self):
        order=self.order()
        with patch.object(accounts,'credit_bucket',side_effect=RuntimeError('injected')):
            with self.assertRaises(RuntimeError):rr.settle(order)
        with accounts._connect() as c:self.assertIsNone(c.execute('SELECT 1 FROM referral_recharge_rewards WHERE order_id=?',(order,)).fetchone())
        rr.settle(order);self.assertEqual(10,self.wallet()['bonus'])


if __name__=='__main__':unittest.main()
