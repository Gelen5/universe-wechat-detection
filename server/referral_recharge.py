"""Additive recharge reward ledger. No client-facing award endpoint.

All mutations use a database transaction and the inviter wallet row lock.
The caller must pass an order ID, never an amount supplied by a browser.
"""
import json
import logging
import uuid
from dataclasses import asdict
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
payments = Table('referral_verified_payments', metadata,
    Column('order_id', String(64), primary_key=True),
    Column('paid_cents', Integer, nullable=False), Column('paid_at', Text, nullable=False),
    Column('trade_no', String(128), nullable=False), Column('proof', Text, nullable=False))
refunds = Table('referral_verified_refunds', metadata,
    Column('request_id', String(128), primary_key=True),
    Column('order_id', String(64), nullable=False, index=True),
    Column('cents', Integer, nullable=False), Column('created_at', Text, nullable=False))
refund_requests = Table('referral_refund_requests', metadata,
    Column('request_id', String(128), primary_key=True), Column('order_id', String(64), nullable=False),
    Column('cents', Integer, nullable=False), Column('status', String(20), nullable=False),
    Column('created_at', Text, nullable=False))
reviews = Table('referral_recharge_reviews', metadata,
    Column('order_id',String(64),primary_key=True),Column('inviter_id',String(64)),
    Column('reason',Text,nullable=False),Column('status',String(16),nullable=False),
    Column('updated_at',Text,nullable=False))


def _review(c, order_id, inviter, reason):
    c.execute('''INSERT INTO referral_recharge_reviews(order_id,inviter_id,reason,status,updated_at)
        VALUES(?,?,?,'pending',?) ON CONFLICT(order_id) DO UPDATE SET
        inviter_id=excluded.inviter_id,reason=excluded.reason,status='pending',updated_at=excluded.updated_at''',
        (order_id,inviter,reason,accounts.utc_now()))
    c.execute('COMMIT')
    return reason


def reserve_refund(order_id, request_id, cents):
    key=order_id+':'+request_id
    if len(key)>128 or cents<=0:raise ValueError('退款金额或请求号无效')
    with accounts._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        lock=' FOR UPDATE' if database.ENGINE.dialect.name=='postgresql' else ''
        order=c.execute('SELECT * FROM alipay_orders WHERE out_trade_no=?'+lock,(order_id,)).fetchone()
        old=c.execute('SELECT * FROM referral_refund_requests WHERE request_id=?',(key,)).fetchone()
        if old:
            if old['cents']!=cents:raise ValueError('同一退款请求号不能改变退款金额')
            c.execute('COMMIT');return old['status']
        pending=c.execute("SELECT COALESCE(SUM(cents),0) FROM referral_refund_requests WHERE order_id=? AND status='pending'",(order_id,)).fetchone()[0]
        if not order or order['status'] not in ('PAID','PARTIAL_REFUNDED') or amount_cents(order['refunded_amount'])+pending+cents>amount_cents(order['total_amount']):
            raise ValueError('可退款金额不足或订单不可退款')
        c.execute("INSERT INTO referral_refund_requests(request_id,order_id,cents,status,created_at) VALUES(?,?,?,'pending',?)",(key,order_id,cents,accounts.utc_now()))
        c.execute('COMMIT');return 'pending'


def confirm_refund(order_id, request_id):
    key=order_id+':'+request_id
    with accounts._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        lock=' FOR UPDATE' if database.ENGINE.dialect.name=='postgresql' else ''
        order=c.execute('SELECT * FROM alipay_orders WHERE out_trade_no=?'+lock,(order_id,)).fetchone()
        req=c.execute('SELECT * FROM referral_refund_requests WHERE request_id=?',(key,)).fetchone()
        if not order or not req:raise ValueError('退款记录不存在')
        if req['status']!='confirmed':
            total=amount_cents(order['refunded_amount'])+req['cents']
            if total>amount_cents(order['total_amount']):raise ValueError('退款累计金额异常，需人工核查')
            c.execute('INSERT OR IGNORE INTO referral_verified_refunds(request_id,order_id,cents,created_at) VALUES(?,?,?,?)',(key,order_id,req['cents'],accounts.utc_now()))
            amount=f'{total//100}.{total%100:02d}'
            c.execute('UPDATE alipay_orders SET refunded_amount=?,status=?,updated_at=? WHERE out_trade_no=?',
                      (amount,'REFUNDED' if total==amount_cents(order['total_amount']) else 'PARTIAL_REFUNDED',accounts.utc_now(),order_id))
            c.execute("UPDATE referral_refund_requests SET status='confirmed' WHERE request_id=?",(key,))
        c.execute('COMMIT')
    reverse_order(order_id)
    # Buyer purchase-point recovery remains separate and replayable. The existing
    # helper uses cumulative targets and transaction keys, not the event count.
    from . import alipay_pay
    fresh=alipay_pay._find_order(order_id)
    alipay_pay._claw_back_refund(fresh, alipay_pay._amount_of(fresh['refunded_amount']),alipay_pay.Decimal('0'),request_id)
    # Reconciliation may confirm a refund after the original HTTP request died.
    # Replay the membership revocation as well as the recharge clawback.
    from . import viral_insights_membership
    if viral_insights_membership.is_membership_order(order_id):
        viral_insights_membership.apply_refund(order_id)


def reconcile_refunds():
    from . import alipay_pay
    with accounts._connect() as c:
        rows=c.execute("SELECT * FROM referral_refund_requests WHERE status IN ('pending','confirmed')").fetchall()
    for row in rows:
        try:
            request_id=row['request_id'][len(row['order_id'])+1:]
            if row['status']=='confirmed':confirm_refund(row['order_id'],request_id);continue
            result=alipay_pay._refund_query(row['order_id'],request_id)
            if result.get('code')=='10000' and result.get('refund_status')=='REFUND_SUCCESS':
                if amount_cents(str(result.get('refund_amount','-1')))!=row['cents']:
                    raise ValueError('平台退款金额不匹配')
                confirm_refund(row['order_id'],request_id)
        except Exception:log.exception('referral.refund_pending request=%s',row['request_id'])


def refund_notice(order_id, request_id):
    """Signed refund notification: never guess whether refund_fee is cumulative."""
    with accounts._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT r.inviter_id,r.invitee_id FROM referrals r JOIN alipay_recharges a ON a.user_id=r.invitee_id WHERE a.out_trade_no=?',(order_id,)).fetchone()
        if not row:c.execute('ROLLBACK');return
        _review(c,order_id,row['inviter_id'],'平台退款通知待核对；退款请求号：'+request_id[:80])
        c.execute('BEGIN IMMEDIATE')
        c.execute("INSERT OR IGNORE INTO referral_reward_risks(invitee_id,reason,status,updated_at) VALUES(?,'平台退款状态待核对','review',?)",(row['invitee_id'],accounts.utc_now()))
        c.execute('COMMIT')
    if request_id:
        try:import_platform_refund(order_id,request_id)
        except Exception:log.exception('referral.external_refund_review order=%s',order_id)


def import_platform_refund(order_id, request_id):
    from . import alipay_pay
    result=alipay_pay._refund_query(order_id,request_id)
    if result.get('code')!='10000' or result.get('refund_status')!='REFUND_SUCCESS':
        raise ValueError('平台尚未确认该退款成功')
    if result.get('out_trade_no') and result['out_trade_no']!=order_id:raise ValueError('退款订单不匹配')
    reserve_refund(order_id,request_id,amount_cents(str(result.get('refund_amount','-1'))))
    confirm_refund(order_id,request_id)
    with accounts._connect() as c:
        c.execute("UPDATE referral_recharge_reviews SET status='resolved',updated_at=? WHERE order_id=?",(accounts.utc_now(),order_id))


def configure(effective_at, enabled=False, rules=Rules()):
    """Explicit administrative rollout, never reset the start on restart."""
    effective = _time(effective_at).isoformat()
    with accounts._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('INSERT OR IGNORE INTO referral_campaign(id,enabled,effective_at,rules_json) VALUES(1,?,?,?)',
                  (int(enabled),effective,json.dumps(asdict(rules))))
        c.execute('COMMIT')


def verified_payment(order_id, result, proof):
    """Internal adapter only, called after signature or authenticated query verification."""
    actual=result.get('buyer_pay_amount')
    when=result.get('gmt_payment') or result.get('send_pay_date')
    trade=result.get('trade_no')
    if actual is None or not when or not trade:
        log.warning('referral.payment_missing_evidence order=%s',order_id)
        with accounts._connect() as c:
            c.execute('BEGIN IMMEDIATE')
            r=c.execute('''SELECT r.inviter_id FROM referrals r JOIN alipay_recharges a ON a.user_id=r.invitee_id
                WHERE a.out_trade_no=?''',(order_id,)).fetchone()
            if r:_review(c,order_id,r['inviter_id'],'needs_payment_provenance')
            else:c.execute('ROLLBACK')
        return
    paid=amount_cents(str(actual)); when=_time(str(when)).isoformat()
    if proof not in ('verified_signature','authenticated_query'):
        raise ValueError('未知支付凭证来源')
    with accounts._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        order=c.execute('SELECT total_amount FROM alipay_orders WHERE out_trade_no=?',(order_id,)).fetchone()
        if (not order or paid>amount_cents(order['total_amount'])
                or (result.get('out_trade_no') and result['out_trade_no']!=order_id)):
            raise ValueError('平台支付凭证与订单不匹配')
        c.execute('INSERT OR IGNORE INTO referral_verified_payments(order_id,paid_cents,paid_at,trade_no,proof) VALUES(?,?,?,?,?)',
                  (order_id,paid,when,str(trade),proof))
        c.execute('COMMIT')


def _recover_bonus(c, row):
    wallet=accounts._locked_wallet(c,row['inviter_id'])
    due=int(row['debt'])
    take=min(due,int(wallet['bonus_balance']))
    if not take:return
    before=int(wallet['balance']); now=accounts.utc_now()
    c.execute('UPDATE wallets SET balance=balance-?,bonus_balance=bonus_balance-?,updated_at=? WHERE user_id=?',
              (take,take,now,row['inviter_id']))
    key='referral-reversal:'+row['order_id']+':'+str(int(row['reversed'])+take)
    c.execute('''INSERT INTO point_transactions(id,user_id,amount,balance_before,balance_after,bucket,kind,source,feature,request_id,note,allocation_json,created_at)
        VALUES(?,?,?,?,?,'bonus','consume','referral_recharge','邀请充值退款冲正',?,?,?,?)''',
        (uuid.uuid4().hex,row['inviter_id'],-take,before,before-take,key,'仅扣赠送积分，未扣购买积分',json.dumps({'bonus':take}),now))
    c.execute('UPDATE referral_recharge_rewards SET debt=debt-?,reversed=reversed+? WHERE order_id=?',
              (take,take,row['order_id']))


def reverse_order(order_id):
    with accounts._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM referral_recharge_rewards WHERE order_id=?',(order_id,)).fetchone()
        if not row:c.execute('ROLLBACK');return
        accounts._locked_wallet(c,row['inviter_id'])
        row=c.execute('SELECT * FROM referral_recharge_rewards WHERE order_id=?',(order_id,)).fetchone()
        total=c.execute('SELECT COALESCE(SUM(cents),0) FROM referral_verified_refunds WHERE order_id=?',(order_id,)).fetchone()[0]
        total=min(int(total),int(row['paid_cents']))
        due=reversal(paid_cents=row['paid_cents'],refunded_cents=total,original_grant=row['granted'],
                     rate_bps=row['rate_bps'],points_per_yuan=row['points_per_yuan'],already_reversed=row['reversed'])
        c.execute('UPDATE referral_recharge_rewards SET refunded_cents=?,debt=? WHERE order_id=?',(total,due,order_id))
        row=c.execute('SELECT * FROM referral_recharge_rewards WHERE order_id=?',(order_id,)).fetchone()
        _recover_bonus(c,row)
        c.execute('COMMIT')


def reconcile():
    reconcile_refunds()
    # Query missing provenance and legacy first-payment dates through Alipay,
    # rather than granting from a local PAID label or model/test data.
    from . import alipay_pay
    with accounts._connect() as c:
        missing=c.execute('''SELECT o.* FROM alipay_orders o JOIN alipay_recharges a ON a.out_trade_no=o.out_trade_no
            JOIN referrals r ON r.invitee_id=a.user_id LEFT JOIN referral_verified_payments v ON v.order_id=o.out_trade_no
            WHERE o.status IN ('PAID','PARTIAL_REFUNDED','REFUNDED') AND v.order_id IS NULL ORDER BY o.created_at LIMIT 50''').fetchall()
    for order in missing:
        try:
            result=alipay_pay._trade_query(order['out_trade_no'])
            if result.get('code')=='10000' and result.get('trade_status') in ('TRADE_SUCCESS','TRADE_FINISHED'):
                if amount_cents(str(result.get('total_amount','-1')))!=amount_cents(order['total_amount']):raise ValueError('平台订单金额不匹配')
                alipay_pay._record_referral_payment(order['out_trade_no'],result,'authenticated_query')
        except Exception:log.exception('referral.history_query_pending order=%s',order['out_trade_no'])
    with accounts._connect() as c:
        ids=[r[0] for r in c.execute('SELECT order_id FROM referral_verified_payments ORDER BY paid_at,order_id').fetchall()]
    for order_id in ids:
        try:
            settle(order_id)
            reverse_order(order_id)
        except Exception:
            log.exception('referral.reconcile_failed order=%s',order_id)


def init_schema():
    metadata.create_all(database.ENGINE)
    # Deployment explicitly activates the fixed UTC campaign through the protected
    # admin API. Restarts never reset eligibility or alter the effective time.


def _time(raw):
    value = datetime.fromisoformat(raw)
    # Existing Alipay _now() stores Beijing wall-clock strings.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone(timedelta(hours=8)))
    return value.astimezone(timezone.utc)


def settle(order_id):
    """Settle verified paid recharges; replayable without inferring legacy proof."""
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
        # Trade number alone is insufficient proof; require durable verified facts.
        verified = c.execute('SELECT * FROM referral_verified_payments WHERE order_id=? AND trade_no=?',
            (order_id,order['trade_no'])).fetchone()
        if not verified:
            c.execute('ROLLBACK'); return 'needs_payment_provenance'
        if verified['paid_cents']<=0:
            c.execute('ROLLBACK');return 'ineligible'
        if _time(verified['paid_at']) < _time(cfg['effective_at']):
            c.execute('ROLLBACK');return 'ineligible'
        ref = c.execute('SELECT * FROM referrals WHERE invitee_id=?',(order['user_id'],)).fetchone()
        if not ref or ref['inviter_id']==ref['invitee_id']:
            c.execute('ROLLBACK'); return 'no_referral'
        inviter=c.execute('SELECT status FROM users WHERE id=?',(ref['inviter_id'],)).fetchone()
        if not inviter or inviter['status']!='active':
            return _review(c,order_id,ref['inviter_id'],'inviter_inactive')
        # Common inviter lock serializes all award/debt modifications across workers.
        accounts._locked_wallet(c,ref['inviter_id'])
        if c.execute('SELECT 1 FROM referral_recharge_rewards WHERE order_id=?',(order_id,)).fetchone():
            c.execute('ROLLBACK'); return 'already_settled'
        risk=c.execute("SELECT 1 FROM referral_reward_risks WHERE invitee_id=? AND status='review'",(ref['invitee_id'],)).fetchone()
        if risk:return _review(c,order_id,ref['inviter_id'],'risk_review')
        history=c.execute('''SELECT o.out_trade_no,v.paid_at FROM alipay_orders o JOIN alipay_recharges r
            ON o.out_trade_no=r.out_trade_no LEFT JOIN referral_verified_payments v ON v.order_id=o.out_trade_no WHERE r.user_id=?
            AND o.status IN ('PAID','PARTIAL_REFUNDED','REFUNDED')
            AND (v.order_id IS NULL OR v.paid_cents>0)''',(order['user_id'],)).fetchall()
        if not history or any(not h['paid_at'] for h in history):
            return _review(c,order_id,ref['inviter_id'],'needs_history_review')
        # An imported Alipay purchase ledger without its order is not evidence of
        # a new first payment. Do not guess after a migration.
        missing=c.execute("""SELECT 1 FROM point_transactions p WHERE p.user_id=? AND p.source='alipay'
            AND p.kind='recharge' AND NOT EXISTS (SELECT 1 FROM alipay_recharges a WHERE p.request_id='alipay:' || a.out_trade_no) LIMIT 1""",(order['user_id'],)).fetchone()
        if missing:return _review(c,order_id,ref['inviter_id'],'needs_history_review')
        first_row=min(history,key=lambda h:(_time(h['paid_at']),h['out_trade_no']))
        first=_time(first_row['paid_at'])
        paid=_time(verified['paid_at'])
        rules=Rules(**json.loads(cfg['rules_json']))
        gross=c.execute('SELECT COALESCE(SUM(granted),0) FROM referral_recharge_rewards WHERE invitee_id=?',
                        (ref['invitee_id'],)).fetchone()[0]
        kind,theoretical,grant=reward(cents=verified['paid_cents'],first_payment=first,
            paid_at=paid,effective_at=_time(cfg['effective_at']),is_first=order_id==first_row['out_trade_no'],
            lifetime_granted=gross,rules=rules)
        if kind in ('expired','ineligible'):
            c.execute("UPDATE referral_recharge_reviews SET status='ineligible',updated_at=? WHERE order_id=?",(accounts.utc_now(),order_id))
            c.execute('COMMIT')
            return kind
        # A refund before award requires review; never pay a gross reward first
        # and create a needless clawback against a previously empty wallet.
        if amount_cents(order['refunded_amount'] or '0'):
            return _review(c,order_id,ref['inviter_id'],'refunded_before_award')
        now=accounts.utc_now()
        c.execute('''INSERT INTO referral_recharge_rewards
            (order_id,referral_id,inviter_id,invitee_id,paid_cents,paid_at,rate_bps,points_per_yuan,
             theoretical,granted,kind,rule_version,status,refunded_cents,reversed,debt,created_at,settled_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,0,?,?)''',
            (order_id,ref['id'],ref['inviter_id'],ref['invitee_id'],verified['paid_cents'],
             paid.isoformat(),rules.first_bps if kind=='first' else rules.repeat_bps,rules.points_per_yuan,
             theoretical,grant,kind,rules.version,'settled',now,now))
        if grant:
            accounts.credit_bucket(c,ref['inviter_id'],grant,'bonus',request_id='referral-recharge:'+order_id,
                source='referral_recharge',feature='邀请充值返奖',note='好友有效充值奖励')
        for debt in c.execute('SELECT * FROM referral_recharge_rewards WHERE inviter_id=? AND debt>0 ORDER BY created_at,order_id',
                              (ref['inviter_id'],)).fetchall():
            _recover_bonus(c,debt)
        c.execute("UPDATE referral_recharge_reviews SET status='resolved',updated_at=? WHERE order_id=?",(now,order_id))
        c.execute('COMMIT')
        return 'settled'


def admin_report(query=''):
    today=datetime.now(timezone(timedelta(hours=8))).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc).isoformat()
    with accounts._connect() as c:
        total=c.execute('SELECT COUNT(*) FROM referrals').fetchone()[0]
        invited_today=c.execute('SELECT COUNT(*) FROM referrals WHERE created_at>=?',(today,)).fetchone()[0]
        stats=c.execute('SELECT COALESCE(SUM(granted),0),COALESCE(SUM(reversed),0),COALESCE(SUM(debt),0) FROM referral_recharge_rewards').fetchone()
        paid=c.execute('''SELECT COUNT(DISTINCT a.user_id),COALESCE(SUM(p.paid_cents),0) FROM referral_verified_payments p
            JOIN alipay_recharges a ON a.out_trade_no=p.order_id JOIN referrals r ON r.invitee_id=a.user_id WHERE p.paid_at>=?''',(today,)).fetchone()
        today_granted=c.execute('SELECT COALESCE(SUM(granted),0) FROM referral_recharge_rewards WHERE created_at>=?',(today,)).fetchone()[0]
        converted=c.execute('''SELECT COUNT(DISTINCT a.user_id) FROM alipay_recharges a JOIN alipay_orders o ON o.out_trade_no=a.out_trade_no
            JOIN referrals r ON r.invitee_id=a.user_id WHERE a.status='CREDITED' AND o.status IN ('PAID','PARTIAL_REFUNDED','REFUNDED')''').fetchone()[0]
        amount=c.execute('SELECT COALESCE(SUM(paid_cents),0) FROM referral_recharge_rewards').fetchone()[0]
        pattern='%'+query.strip()+'%'
        rows=c.execute('''SELECT * FROM referral_recharge_rewards WHERE order_id LIKE ? OR inviter_id LIKE ? OR invitee_id LIKE ? ORDER BY created_at DESC LIMIT 100''',(pattern,pattern,pattern)).fetchall()
        pending=c.execute("SELECT * FROM referral_recharge_reviews WHERE status='pending' ORDER BY updated_at DESC LIMIT 100").fetchall()
        risks=c.execute("SELECT * FROM referral_reward_risks WHERE status='review' LIMIT 100").fetchall()
        refunds_pending=c.execute("SELECT request_id,order_id,cents,status,created_at FROM referral_refund_requests WHERE status='pending' LIMIT 100").fetchall()
    return {'referrals':total,'today_invites':invited_today,'today_paid_friends':paid[0],'today_paid_cents':paid[1],
        'today_granted':today_granted,'points_granted':stats[0],'reversed_points':stats[1],'pending_reversal_points':stats[2],
        'conversion_rate':converted/total if total else 0,'reward_points_per_yuan':stats[0]*100/amount if amount else 0,
        'records':[dict(r) for r in rows],'reviews':[dict(r) for r in pending],
        'risks':[dict(r) for r in risks],'pending_refunds':[dict(r) for r in refunds_pending]}


from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from fastapi.responses import HTMLResponse
router=APIRouter(tags=['referral-recharge-admin'])

class CampaignControl(BaseModel):
    enabled:bool

class RefundReconcile(BaseModel):
    order_id:str
    request_id:str

@router.post('/api/admin/referral-recharge/refund-reconcile')
def refund_reconcile_api(payload:RefundReconcile,request:Request):
    actor=_admin(request,True)
    try:import_platform_refund(payload.order_id,payload.request_id)
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    with accounts._connect() as c:
        c.execute('INSERT INTO admin_actions(id,operator_id,action,detail_json,created_at) VALUES(?,?,?,?,?)',
            (uuid.uuid4().hex,actor['id'],'referral_refund_reconcile',json.dumps({'order_id':payload.order_id,'request_id':payload.request_id}),accounts.utc_now()))
    return {'status':'reconciled'}


@router.post('/api/admin/referral-recharge/campaign')
def campaign_control(payload:CampaignControl,request:Request):
    actor=_admin(request,True)
    from . import alipay_pay
    if payload.enabled and alipay_pay.load_payment_config().get('gateway')!=alipay_pay.PRODUCTION_GATEWAY:
        raise HTTPException(409,'只有真实生产支付通道可以开启活动')
    configure(accounts.utc_now(),False)
    with accounts._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('UPDATE referral_campaign SET enabled=? WHERE id=1',(int(payload.enabled),))
        c.execute('INSERT INTO admin_actions(id,operator_id,action,detail_json,created_at) VALUES(?,?,?,?,?)',
            (uuid.uuid4().hex,actor['id'],'referral_campaign_switch',json.dumps({'enabled':payload.enabled}),accounts.utc_now()))
        cfg=dict(c.execute('SELECT * FROM referral_campaign WHERE id=1').fetchone())
        c.execute('COMMIT')
    return {'enabled':bool(cfg['enabled']),'effective_at':cfg['effective_at'],'rules':json.loads(cfg['rules_json'])}


def _admin(request, mutation=False):
    user=accounts.require_admin(request)
    if user.get('impersonation'):raise HTTPException(403,'请退出用户代管模式')
    if mutation and request.headers.get('origin'):
        from urllib.parse import urlparse
        if urlparse(request.headers['origin']).netloc!=request.headers.get('host'):
            raise HTTPException(403,'请求来源无效')
    return user


@router.get('/api/admin/referral-recharge')
def report_api(request:Request,q:str=''):
    _admin(request)
    return admin_report(q)


@router.post('/api/admin/referral-recharge/reconcile')
def reconcile_api(request:Request):
    _admin(request,True)
    reconcile()
    return {'status':'completed','report':admin_report()}


@router.post('/api/admin/referral-recharge/risk/{invitee_id}/approve')
def approve_risk(invitee_id:str,request:Request):
    actor=_admin(request,True)
    with accounts._connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE referral_reward_risks SET status='approved',updated_at=? WHERE invitee_id=?",(accounts.utc_now(),invitee_id))
        c.execute('INSERT INTO admin_actions(id,operator_id,target_user_id,action,detail_json,created_at) VALUES(?,?,?,?,?,?)',
                  (uuid.uuid4().hex,actor['id'],invitee_id,'approve_referral_risk','{}',accounts.utc_now()))
        c.execute('COMMIT')
    reconcile()
    return {'status':'approved'}


@router.get('/admin/referral-recharge',response_class=HTMLResponse)
def report_page(request:Request,q:str=''):
    _admin(request)
    from .wallet_page import _page
    import html
    report=admin_report(q)
    esc=lambda s:html.escape(str(s),quote=True)
    labels={'today_invites':'今日邀请注册','today_paid_friends':'今日充值好友','today_paid_cents':'今日充值金额（分）',
        'today_granted':'今日发放积分','points_granted':'累计发放积分','pending_reversal_points':'待冲正积分',
        'reversed_points':'已冲正积分','conversion_rate':'有效充值转化率','reward_points_per_yuan':'每元充值返奖积分'}
    cards=''.join(f'<article><small>{label}</small><b>{esc(report[key])}</b></article>' for key,label in labels.items())
    rows=''.join('<tr>'+''.join(f'<td>{esc(r[k])}</td>' for k in ('order_id','inviter_id','invitee_id','paid_cents','kind','granted','reversed','debt'))+'</tr>' for r in report['records'])
    risks=''.join(f'<li>{esc(r["invitee_id"])}：{esc(r["reason"])} <button data-approve="{esc(r["invitee_id"])}">核查通过</button></li>' for r in report['risks'])
    details=esc(json.dumps({'待核查':report['reviews'],'待确认退款':report['pending_refunds']},ensure_ascii=False,indent=2))
    body=f'''<a href="/invite">← 邀请好友</a><h1>邀请充值返奖管理</h1><p>仅管理员可见。金额单位为整数分；待确认退款保留额度，不重复请求退款。</p>
    <style>.rgrid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}article{{padding:16px;background:#edf7f0;border-radius:14px}}article b{{display:block;font-size:24px}}td,th{{padding:10px;border-bottom:1px solid #d4e4d9;white-space:nowrap}}button,input{{font:inherit;padding:10px;border:1px solid #c8ddcf;border-radius:10px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}</style>
    <div class="rgrid">{cards}</div><p><button id="reconcile">重新对账</button><span id="status" role="status"></span></p>
    <form><input name="q" placeholder="邀请人ID、好友ID或订单号" value="{esc(q)}"><button>查询</button></form>
    <div style="overflow:auto"><table><tr><th>订单</th><th>邀请人</th><th>好友</th><th>实付分</th><th>类型</th><th>发放</th><th>冲正</th><th>债务</th></tr>{rows}</table></div>
    <h2>风险核查</h2><ul>{risks or '<li>暂无</li>'}</ul><h2>未结算与退款异常</h2><pre>{details}</pre>
    <h2>核对平台已成功退款</h2><p>仅查询并同步平台退款结果，不会发起新的退款。</p><form id="refund-check"><input name="order_id" placeholder="充值订单号" required><input name="request_id" placeholder="平台退款请求号" required><button>核对退款</button></form>
    <script>document.querySelector('#refund-check').onsubmit=async e=>{{e.preventDefault();const b=e.target.querySelector('button');b.disabled=true;try{{const r=await fetch('/api/admin/referral-recharge/refund-reconcile',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(Object.fromEntries(new FormData(e.target)))}});if(r.ok)location.reload();else document.querySelector('#status').textContent='核对未完成，请检查订单、退款号及平台状态';}}finally{{b.disabled=false;}}}};</script>
    <script>async function act(url){{document.querySelector('#status').textContent='处理中';const r=await fetch(url,{{method:'POST'}});if(r.ok)location.reload();else document.querySelector('#status').textContent='操作失败，请核对权限和服务日志';}}document.querySelector('#reconcile').onclick=()=>act('/api/admin/referral-recharge/reconcile');document.querySelectorAll('[data-approve]').forEach(b=>b.onclick=()=>act('/api/admin/referral-recharge/risk/'+encodeURIComponent(b.dataset.approve)+'/approve'));</script>'''
    return HTMLResponse(_page('邀请充值返奖管理',body),headers={'Cache-Control':'no-store'})
