"""Independent agent attribution and read-only recharge reporting."""
import logging
import secrets
import sqlite3
from decimal import Decimal
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from . import accounts
from .owner_revenue import require_owner

router = APIRouter()
log = logging.getLogger(__name__)
STATIC = Path(__file__).resolve().parent.parent / 'static'

class AgentPayload(BaseModel):
    email: str = Field(min_length=5, max_length=254)

class ActivePayload(BaseModel):
    active: bool


def bind_signup(user_id: str, code: str):
    """Called exclusively from a successful registration, never from login."""
    if not code or len(code) > 32:
        return 'none'
    try:
        with accounts._connect() as c:
            result = c.execute('''INSERT OR IGNORE INTO agent_customers(customer_id,agent_id,created_at)
                SELECT ?,user_id,? FROM agent_profiles WHERE code=? AND active=? AND user_id<>?''',
                (user_id, accounts.utc_now(), code, True, user_id))
            return 'bound' if result.rowcount else 'ignored'
    except Exception:
        log.exception('agent signup attribution failed user=%s', user_id)
        return 'error'


@router.get('/agent', include_in_schema=False)
def agent_page(request: Request):
    user = accounts.require_user(request)
    with accounts._connect() as c:
        row = c.execute('SELECT user_id FROM agent_profiles WHERE user_id=?', (user['id'],)).fetchone()
    if not row:
        raise HTTPException(403, '仅代理可访问')
    return FileResponse(STATIC / 'agent.html', headers={'Cache-Control': 'no-store'})


@router.get('/api/agent/me')
def agent_me(request: Request):
    user = accounts.require_user(request)
    with accounts._connect() as c:
        profile = c.execute('SELECT code,active FROM agent_profiles WHERE user_id=?', (user['id'],)).fetchone()
    if not profile:
        raise HTTPException(403, '仅代理可访问')
    return {'code': profile['code'], 'active': bool(profile['active'])}


@router.get('/admin/agents', include_in_schema=False)
def admin_page(request: Request):
    require_owner(request)
    return FileResponse(STATIC / 'agent-admin.html', headers={'Cache-Control': 'no-store'})


@router.post('/api/admin/agents')
def add_agent(payload: AgentPayload, request: Request):
    require_owner(request)
    email = payload.email.strip().lower()
    with accounts._connect() as c:
        user = c.execute('SELECT id,status FROM users WHERE email=?', (email,)).fetchone()
        if not user:
            raise HTTPException(404, '该邮箱没有注册账号')
        if user['status'] != 'active':
            raise HTTPException(409, '该用户账号未启用')
        try:
            c.execute('INSERT INTO agent_profiles(user_id,code,active,created_at) VALUES(?,?,?,?)',
                      (user['id'], secrets.token_hex(12).upper(), True, accounts.utc_now()))
        except (IntegrityError, sqlite3.IntegrityError):
            raise HTTPException(409, '该用户已经是代理')
    return {'status': 'ok'}


@router.post('/api/admin/agents/{user_id}/active')
def set_agent_active(user_id: str, payload: ActivePayload, request: Request):
    require_owner(request)
    with accounts._connect() as c:
        result = c.execute('UPDATE agent_profiles SET active=? WHERE user_id=?', (payload.active, user_id))
        if not result.rowcount:
            raise HTTPException(404, '代理不存在')
    return {'status': 'ok'}


@router.get('/api/admin/agents')
def list_agents(request: Request):
    require_owner(request)
    with accounts._connect() as c:
        rows = c.execute('''SELECT p.user_id,p.code,p.active,p.created_at,u.email,u.display_name,
            (SELECT COUNT(*) FROM agent_customers a WHERE a.agent_id=p.user_id) AS customers
            FROM agent_profiles p JOIN users u ON u.id=p.user_id ORDER BY p.created_at DESC''').fetchall()
    return {'agents': [dict(r) for r in rows]}


@router.get('/api/admin/agents/{user_id}/orders')
def agent_orders(user_id: str, request: Request, page: int = 1):
    require_owner(request)
    return _orders(user_id, page, mask_email=False)


@router.get('/api/agent/orders')
def my_orders(request: Request, page: int = 1):
    user = accounts.require_user(request)
    return _orders(user['id'], page, mask_email=True)


def _orders(user_id: str, page: int, mask_email: bool):
    page = max(1, page)
    with accounts._connect() as c:
        profile = c.execute('SELECT user_id FROM agent_profiles WHERE user_id=?', (user_id,)).fetchone()
        if not profile:
            raise HTTPException(403 if mask_email else 404, '仅代理可访问' if mask_email else '代理不存在')
        summary_rows = c.execute("""SELECT o.total_amount,o.refunded_amount,r.user_id FROM agent_customers a JOIN alipay_recharges r ON r.user_id=a.customer_id JOIN alipay_orders o ON o.out_trade_no=r.out_trade_no WHERE a.agent_id=? AND o.status IN ('PAID','PARTIAL_REFUNDED','REFUNDED') AND r.status='CREDITED'""", (user_id,)).fetchall()
        total = c.execute('''SELECT COUNT(*) FROM agent_customers a JOIN alipay_recharges r ON r.user_id=a.customer_id
            JOIN alipay_orders o ON o.out_trade_no=r.out_trade_no
            WHERE a.agent_id=? AND o.status IN ('PAID','PARTIAL_REFUNDED','REFUNDED') AND r.status='CREDITED' ''', (user_id,)).fetchone()[0]
        rows = c.execute('''SELECT o.out_trade_no,o.total_amount,o.refunded_amount,o.status,o.paid_at,
            u.email FROM agent_customers a JOIN users u ON u.id=a.customer_id
            JOIN alipay_recharges r ON r.user_id=a.customer_id
            JOIN alipay_orders o ON o.out_trade_no=r.out_trade_no
            WHERE a.agent_id=? AND o.status IN ('PAID','PARTIAL_REFUNDED','REFUNDED') AND r.status='CREDITED'
            ORDER BY o.created_at DESC LIMIT ? OFFSET ?''', (user_id, 50, (page-1)*50)).fetchall()
    gross = sum((Decimal(row['total_amount']) for row in summary_rows), Decimal('0'))
    refunded = sum((Decimal(row['refunded_amount']) for row in summary_rows), Decimal('0'))
    orders = [dict(r) for r in rows]
    if mask_email:
        for order in orders:
            local, _, domain = order['email'].partition('@')
            order['email'] = (local[:1] + '***@' + domain) if domain else '***'
    return {'orders': orders, 'page': page, 'total': total,
            'paid_customers': len({row['user_id'] for row in summary_rows}),
            'order_total': str(gross), 'refunded_total': str(refunded)}


@router.get('/api/admin/agents/{user_id}/estimate')
def settlement_estimate(user_id: str, request: Request, day: str, rate_bps: int):
    require_owner(request)
    try:
        selected = date.fromisoformat(day)
        if selected.isoformat() != day:
            raise ValueError()
        following = selected + timedelta(days=1)
    except (ValueError, OverflowError):
        raise HTTPException(422, '日期格式应为 YYYY-MM-DD')
    if not 0 <= rate_bps <= 10000:
        raise HTTPException(422, '分成比例应在 0% 至 100% 之间')
    start = selected.isoformat() + ' 00:00:00'
    end = following.isoformat() + ' 00:00:00'
    with accounts._connect() as c:
        if not c.execute('SELECT user_id FROM agent_profiles WHERE user_id=?', (user_id,)).fetchone():
            raise HTTPException(404, '代理不存在')
        rows = c.execute('''SELECT o.total_amount,o.refunded_amount FROM agent_customers a
            JOIN alipay_recharges r ON r.user_id=a.customer_id
            JOIN alipay_orders o ON o.out_trade_no=r.out_trade_no
            WHERE a.agent_id=? AND r.status='CREDITED'
              AND o.status IN ('PAID','PARTIAL_REFUNDED','REFUNDED')
              AND o.paid_at>=? AND o.paid_at<?''', (user_id, start, end)).fetchall()
        missing_time = c.execute('''SELECT COUNT(*) FROM agent_customers a
            JOIN alipay_recharges r ON r.user_id=a.customer_id
            JOIN alipay_orders o ON o.out_trade_no=r.out_trade_no
            WHERE a.agent_id=? AND r.status='CREDITED'
              AND o.status IN ('PAID','PARTIAL_REFUNDED','REFUNDED')
              AND (o.paid_at IS NULL OR o.paid_at='')''', (user_id,)).fetchone()[0]
    def cents(value):
        amount = Decimal(str(value or '0')) * 100
        if amount != amount.to_integral_value() or amount < 0:
            raise HTTPException(500, '订单金额异常，请人工核对')
        return int(amount)
    gross = sum(cents(row['total_amount']) for row in rows)
    refunded = sum(cents(row['refunded_amount']) for row in rows)
    net = gross - refunded
    if net < 0:
        raise HTTPException(500, '订单退款金额异常，请人工核对')
    estimate = (net * rate_bps + 5000) // 10000
    return {'day': day, 'rate_bps': rate_bps, 'orders': len(rows), 'missing_paid_time': missing_time, 'order_cents': gross,
            'refunded_cents': refunded, 'net_cents': net, 'estimate_cents': estimate}
