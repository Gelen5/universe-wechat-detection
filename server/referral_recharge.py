"""Additive recharge reward ledger. No client-facing award endpoint.

All mutations use a database transaction and the inviter wallet row lock.
The caller must pass an order ID, never an amount supplied by a browser.
"""
import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import Column, Integer, MetaData, String, Table, Text
from . import accounts, database
from .referral_reward_rules import Rules, amount_cents, reward, reversal

log = logging.getLogger(__name__)
metadata = MetaData()
campaign = Table('referral_campaign', metadata,
    Column('id', Integer, primary_key=True), Column('enabled', Integer, nullable=False),
    Column('effective_at', Text, nullable=False), Column('rules_json', Text, nullable=False))
rewards = Table('referral_recharge_rewards', metadata,
    Column('order_id', String(64), primary_key=True),
    Column('referral_id', String(64), nullable=False),
    Column('inviter_id', String(64), nullable=False, index=True),
    Column('invitee_id', String(64), nullable=False, index=True),
    Column('paid_cents', Integer, nullable=False), Column('paid_at', Text, nullable=False),
    Column('rate_bps', Integer, nullable=False), Column('points_per_yuan', Integer, nullable=False),
    Column('theoretical', Integer, nullable=False), Column('granted', Integer, nullable=False),
    Column('kind', String(16), nullable=False), Column('rule_version', String(32), nullable=False),
    Column('status', String(32), nullable=False), Column('refunded_cents', Integer, nullable=False),
    Column('reversed', Integer, nullable=False), Column('debt', Integer, nullable=False),
    Column('created_at', Text, nullable=False), Column('settled_at', Text))


def init_schema():
    metadata.create_all(database.ENGINE)
    # Deliberately no campaign auto-activation: deployment must explicitly insert
    # the approved, fixed UTC start time and version after migration acceptance.


def _time(raw):
    value = datetime.fromisoformat(raw)
    # Existing Alipay _now() stores Beijing wall-clock strings.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone(timedelta(hours=8)))
    return value.astimezone(timezone.utc)


def settle(order_id):
    """Settle from persisted paid recharge; safe to replay after crediting.

    Only usable once trusted payment provenance is added by the payment adapter.
    The migration intentionally does not infer provenance from legacy PAID rows.
    """
    with accounts._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        cfg = c.execute('SELECT * FROM referral_campaign WHERE id=1').fetchone()
        if not cfg or not cfg['enabled']:
            c.execute('ROLLBACK'); return 'disabled'
        order = c.execute('''SELECT o.*,r.user_id,r.status recharge_status
            FROM alipay_orders o JOIN alipay_recharges r ON r.out_trade_no=o.out_trade_no
            WHERE o.out_trade_no=?''',(order_id,)).fetchone()
        if not order or order['status'] not in ('PAID','PARTIAL_REFUNDED','REFUNDED') or order['recharge_status']!='CREDITED':
            c.execute('ROLLBACK'); return 'not_paid'
        # Trade number alone is not sufficient proof (test/manual data may have
        # one). Production activation is blocked until durable verified events
        # exist and the payment adapter supplies the required provenance.
        verified = c.execute('''SELECT 1 FROM alipay_notify_events
            WHERE out_trade_no=? AND trade_no=? AND trade_status IN ('TRADE_SUCCESS','TRADE_FINISHED') LIMIT 1''',
            (order_id,order['trade_no'])).fetchone()
        if not verified:
            c.execute('ROLLBACK'); return 'needs_payment_provenance'
        ref = c.execute('SELECT * FROM referrals WHERE invitee_id=?',(order['user_id'],)).fetchone()
        if not ref or ref['inviter_id']==ref['invitee_id']:
            c.execute('ROLLBACK'); return 'no_referral'
        # Common inviter lock serializes all award/debt modifications across workers.
        accounts._locked_wallet(c,ref['inviter_id'])
        if c.execute('SELECT 1 FROM referral_recharge_rewards WHERE order_id=?',(order_id,)).fetchone():
            c.execute('ROLLBACK'); return 'already_settled'
        history=c.execute('''SELECT o.paid_at FROM alipay_orders o JOIN alipay_recharges r
            ON o.out_trade_no=r.out_trade_no WHERE r.user_id=?
            AND o.status IN ('PAID','PARTIAL_REFUNDED','REFUNDED')''',(order['user_id'],)).fetchall()
        if not history or any(not h['paid_at'] for h in history):
            c.execute('ROLLBACK'); return 'needs_history_review'
        first=min(_time(h['paid_at']) for h in history)
        paid=_time(order['paid_at'])
        rules=Rules(**json.loads(cfg['rules_json']))
        gross=c.execute('SELECT COALESCE(SUM(granted),0) FROM referral_recharge_rewards WHERE invitee_id=?',
                        (ref['invitee_id'],)).fetchone()[0]
        kind,theoretical,grant=reward(cents=amount_cents(order['total_amount']),first_payment=first,
            paid_at=paid,effective_at=_time(cfg['effective_at']),is_first=paid==first,
            lifetime_granted=gross,rules=rules)
        if kind in ('expired','ineligible'):
            c.execute('ROLLBACK'); return kind
        # Until debt offsets and verified refund events are integrated, refuse
        # activation for refunded orders rather than issuing unsafe rewards.
        if amount_cents(order['refunded_amount'] or '0'):
            c.execute('ROLLBACK'); return 'needs_refund_review'
        if c.execute('SELECT 1 FROM referral_recharge_rewards WHERE inviter_id=? AND debt>0',
                     (ref['inviter_id'],)).fetchone():
            c.execute('ROLLBACK'); return 'needs_debt_settlement'
        now=accounts.utc_now()
        c.execute('''INSERT INTO referral_recharge_rewards
            (order_id,referral_id,inviter_id,invitee_id,paid_cents,paid_at,rate_bps,points_per_yuan,
             theoretical,granted,kind,rule_version,status,refunded_cents,reversed,debt,created_at,settled_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,?,?)''',
            (order_id,ref['id'],ref['inviter_id'],ref['invitee_id'],amount_cents(order['total_amount']),
             paid.isoformat(),rules.first_bps if kind=='first' else rules.repeat_bps,rules.points_per_yuan,
             theoretical,grant,kind,rules.version,'settled',now,now))
        if grant:
            accounts.credit_bucket(c,ref['inviter_id'],grant,'bonus',request_id='referral-recharge:'+order_id,
                source='referral_recharge',feature='邀请充值返奖',note='好友有效充值奖励')
        c.execute('COMMIT')
        return 'settled'
