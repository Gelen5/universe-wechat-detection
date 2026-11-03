"""Unified viral-insights trial, membership, and order service."""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from . import accounts, database

router = APIRouter(tags=["viral-insights-membership"])
metadata = MetaData()

trials = Table("viral_insights_trials", metadata,
    Column("user_id", String(64), primary_key=True),
    Column("activated_at", String(40), nullable=False),
    Column("expires_at", String(40), nullable=False))
orders = Table("viral_insights_membership_orders", metadata,
    Column("out_trade_no", String(64), primary_key=True),
    Column("user_id", String(64), nullable=False),
    Column("package_id", String(16), nullable=False),
    Column("amount", String(8), nullable=False),
    Column("days", Integer, nullable=False),
    Column("status", String(24), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("paid_at", String(40)),
    Column("started_at", String(40)),
    Column("expires_at", String(40)),
    Column("refunded_at", String(40)))
Index("idx_viral_membership_user_status", orders.c.user_id, orders.c.status)
Index("idx_viral_membership_created", orders.c.status, orders.c.created_at)

PACKAGES = (
    {"id": "week", "name": "周卡", "price": "9.90", "days": 7},
    {"id": "month", "name": "月卡", "price": "29.90", "days": 30},
    {"id": "year", "name": "年卡", "price": "199.00", "days": 365},
)
TRIAL_HOURS = 5

def enabled() -> bool:
    return os.getenv("VIRAL_INSIGHTS_PAYWALL_ENABLED", "0").strip() == "1"

def init_schema() -> None:
    """Idempotent startup schema.

    This repo's production deploy path (`up -d --no-deps`) never runs the compose
    `migrate` service: the live PostgreSQL `alembic_version` is far behind while
    the real tables are created by each module's `init_schema()` at startup
    (`checkfirst=True`). Membership tables must follow the same convention,
    otherwise the paywall would 500 on a database without them. The Alembic
    revision `20261104_0013` remains the versioned source of truth for
    environments that do run migrations.
    """
    metadata.create_all(database.ENGINE, checkfirst=True)

def _db_now(connection) -> datetime:
    """Database-server UTC time; never the client clock or app process clock."""
    value = connection.exec_driver_sql("SELECT CURRENT_TIMESTAMP").scalar_one()
    if not isinstance(value, datetime):
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)

def _iso(value: datetime | None) -> str | None:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()

def _state(user_id: str, connection=None) -> dict[str, Any]:
    own = connection is None
    connection = connection or database.ENGINE.connect()
    try:
        now = _db_now(connection)
        from .models import users_table
        owner = connection.execute(select(users_table.c.id).where(
            users_table.c.id == user_id, users_table.c.role == 'admin',
            func.lower(users_table.c.email) == accounts.OWNER_EMAIL)).first() is not None
        trial = connection.execute(select(trials).where(trials.c.user_id == user_id)).mappings().first()
        paid = connection.execute(select(orders).where(orders.c.user_id == user_id,
            orders.c.status == "PAID").order_by(orders.c.created_at.desc())).mappings().all()
        ends = [_parse(order["expires_at"]) for order in paid if order.get("expires_at")]
        paid_until = max(ends) if ends else None
        trial_until = _parse(trial["expires_at"]) if trial else None
        pending_cutoff = (now - timedelta(minutes=30)).isoformat()
        latest_order = connection.execute(select(orders).where(orders.c.user_id == user_id,
            orders.c.status.in_(("CREATED", "PENDING_PAYMENT")), orders.c.created_at >= pending_cutoff)
            .order_by(orders.c.created_at.desc()).limit(1)).mappings().first()
        ever_purchased = connection.execute(select(orders.c.out_trade_no).where(
            orders.c.user_id == user_id, orders.c.status.in_(("PAID", "REFUNDED"))).limit(1)).first() is not None
        active = bool(owner or (paid_until and paid_until > now) or (trial_until and trial_until > now))
        status = "owner_permanent" if owner else "member_active" if paid_until and paid_until > now else (
            "trial_active" if trial_until and trial_until > now else (
            "member_expired" if ever_purchased else "trial_expired" if trial else "trial_available"))
        return {"enabled": enabled(), "status": status, "active": active,
            "trial_activated_at": trial["activated_at"] if trial else None,
            "trial_expires_at": trial["expires_at"] if trial else None,
            "membership_expires_at": _iso(paid_until),
            "pending_order": {k: latest_order[k] for k in ("out_trade_no", "package_id", "amount", "created_at")}
                             if latest_order else None,
            "server_time": _iso(now)}
    finally:
        if own: connection.close()

def has_access(user_id: str | None) -> bool:
    if not enabled(): return True
    if not user_id: return False
    return _state(str(user_id))["active"]

def require_access(request: Request) -> None:
    user = getattr(request.state, "user", None)
    if not enabled(): return
    if not user:
        raise HTTPException(403, detail={"code":"INSIGHTS_MEMBERSHIP_REQUIRED", "reason":"login_required"})
    if not has_access(user["id"]):
        raise HTTPException(403, detail={"code":"INSIGHTS_MEMBERSHIP_REQUIRED", "reason":"membership_required"})

def preview_limit() -> int:
    try: return max(1, min(10, int(os.getenv("VIRAL_INSIGHTS_PREVIEW_LIMIT", "5"))))
    except ValueError: return 5

@router.get("/api/viral-insights/membership")
def membership_status(request: Request):
    user = getattr(request.state, "user", None)
    if not user: return {"enabled":enabled(), "status":"logged_out", "active":False,
                         "packages":[dict(p) for p in PACKAGES]}
    return {**_state(user["id"]), "packages":[dict(p) for p in PACKAGES]}

@router.post("/api/viral-insights/trial/activate")
def activate_trial(request: Request):
    user = accounts.require_user(request)
    uid = str(user["id"])
    if not enabled(): raise HTTPException(409, "会员访问控制尚未启用")
    with database.ENGINE.begin() as connection:
        _lock_user(connection, uid)
        if connection.execute(select(orders.c.out_trade_no).where(
            orders.c.user_id==uid,orders.c.status.in_(("PAID","REFUNDED"))).limit(1)).first():
            raise HTTPException(409, "购买过会员的账号不再具备试用资格")
        now = _db_now(connection)
        activated = now.isoformat()
        expires = (now + timedelta(hours=TRIAL_HOURS)).isoformat()
        try:
            # Savepoint: a concurrent duplicate insert must not abort the outer transaction.
            with connection.begin_nested():
                connection.execute(insert(trials).values(user_id=uid, activated_at=activated, expires_at=expires))
        except IntegrityError:
            pass
    state = _state(uid)
    return {**state, "activated": state.get("trial_activated_at") == activated}

class OrderRequest(BaseModel):
    package_id: str = Field(min_length=1, max_length=16)

@router.get("/api/viral-insights/packages")
def package_list():
    return {"packages":[dict(p) for p in PACKAGES], "currency":"CNY", "auto_renew":False}

@router.post("/api/viral-insights/orders")
def create_membership_order(payload: OrderRequest, request: Request):
    user = accounts.require_user(request)
    package = next((p for p in PACKAGES if p["id"] == payload.package_id), None)
    if not package: raise HTTPException(404, "套餐不存在")
    if not enabled(): raise HTTPException(409, "会员销售尚未开放")
    from . import alipay_pay
    try: config = alipay_pay.load_payment_config()
    except alipay_pay.PaymentConfigError as exc: raise HTTPException(503, str(exc)) from exc
    oid = "VI" + secrets.token_hex(14).upper()
    with database.ENGINE.begin() as connection:
        now = _db_now(connection).isoformat()
        connection.execute(insert(alipay_pay.alipay_orders).values(out_trade_no=oid,
            app_id=config["app_id"], subject="爆款情报会员·"+package["name"],
            total_amount=package["price"], status="CREATED", refunded_amount="0.00",
            created_at=alipay_pay._now(), updated_at=alipay_pay._now()))
        connection.execute(insert(orders).values(out_trade_no=oid, user_id=str(user["id"]),
            package_id=package["id"], amount=package["price"], days=package["days"], status="PENDING_PAYMENT", created_at=now))
    try:
        form = alipay_pay._page_pay_form(oid, package["price"], "爆款情报会员·"+package["name"],
            return_url=alipay_pay._result_url(request), notify_url=alipay_pay._notify_url())
    except Exception as exc:
        with database.ENGINE.begin() as connection:
            connection.execute(update(orders).where(orders.c.out_trade_no==oid).values(status="FAILED"))
            connection.execute(update(alipay_pay.alipay_orders).where(alipay_pay.alipay_orders.c.out_trade_no==oid).values(status="FAILED",updated_at=alipay_pay._now()))
        raise HTTPException(502, "支付宝下单失败") from exc
    return {"out_trade_no":oid,"total_amount":package["price"],"form_html":form,"package":dict(package)}

@router.get("/api/viral-insights/orders/{out_trade_no}")
def own_order(out_trade_no: str, request: Request):
    user = accounts.require_user(request)
    with database.ENGINE.connect() as connection:
        row=connection.execute(select(orders).where(orders.c.out_trade_no==out_trade_no,
            orders.c.user_id==str(user["id"]))).mappings().first()
    if not row: raise HTTPException(404,"订单不存在")
    return {key:row[key] for key in ("out_trade_no","package_id","amount","days","status","created_at","paid_at","refunded_at")}

def order_summary(out_trade_no: str) -> dict[str, Any] | None:
    with database.ENGINE.connect() as connection:
        row = connection.execute(select(orders).where(orders.c.out_trade_no == out_trade_no)).mappings().first()
    return dict(row) if row else None

def is_membership_order(out_trade_no: str) -> bool:
    with database.ENGINE.connect() as connection:
        return connection.execute(select(orders.c.out_trade_no).where(
            orders.c.out_trade_no == out_trade_no)).first() is not None

def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def _lock_user(connection, user_id: str) -> None:
    """Serialize every entitlement write for one user (PostgreSQL row lock)."""
    if connection.dialect.name == "postgresql":
        from .models import users_table
        connection.execute(select(users_table.c.id).where(users_table.c.id == user_id).with_for_update()).first()

def _recompute(connection, user_id: str) -> None:
    """Rebuild every paid window in payment order.

    Each order starts at the later of its payment time, the trial end, and the
    previous paid window; refunds therefore pull later windows forward rather
    than leaving a hole.
    """
    trial = connection.execute(select(trials).where(trials.c.user_id == user_id)).mappings().first()
    trial_end = _parse(trial["expires_at"]) if trial else None
    paid = connection.execute(select(orders).where(orders.c.user_id == user_id, orders.c.status == "PAID")
                              .order_by(orders.c.paid_at.asc(), orders.c.out_trade_no.asc())).mappings().all()
    cursor = None
    for row in paid:
        paid_at = _parse(row["paid_at"])
        start = max(value for value in (paid_at, trial_end, cursor) if value is not None)
        cursor = start + timedelta(days=int(row["days"]))
        connection.execute(update(orders).where(orders.c.out_trade_no == row["out_trade_no"])
                           .values(started_at=start.isoformat(), expires_at=cursor.isoformat()))

def apply_paid(out_trade_no: str, trade_no: str | None = None) -> bool:
    """Idempotently grant this membership order; called only after Alipay verification."""
    with database.ENGINE.begin() as connection:
        row = connection.execute(select(orders).where(orders.c.out_trade_no == out_trade_no)).mappings().first()
        if not row:
            return False
        _lock_user(connection, row["user_id"])
        query = select(orders).where(orders.c.out_trade_no == out_trade_no)
        if connection.dialect.name == "postgresql":
            query = query.with_for_update()
        row = connection.execute(query).mappings().first()
        if row["status"] in ("PAID", "REFUNDED"):
            return row["status"] == "PAID"
        now = _db_now(connection)
        connection.execute(update(orders).where(orders.c.out_trade_no == out_trade_no)
                           .values(status="PAID", paid_at=now.isoformat()))
        _recompute(connection, row["user_id"])
        from . import alipay_pay
        values = {"status": "PAID", "paid_at": alipay_pay._now(), "updated_at": alipay_pay._now()}
        if trade_no:
            values["trade_no"] = trade_no
        connection.execute(update(alipay_pay.alipay_orders)
                           .where(alipay_pay.alipay_orders.c.out_trade_no == out_trade_no,
                                  alipay_pay.alipay_orders.c.status.notin_(("REFUNDED", "PARTIAL_REFUNDED")))
                           .values(**values))
        return True

def apply_refund(out_trade_no: str) -> bool:
    """Revoke one paid membership order and recompute the user's remaining windows.

    Any confirmed refund (full or partial) revokes the whole order: a membership
    period cannot be split by amount. Repeated refunds return False and change nothing.
    """
    with database.ENGINE.begin() as connection:
        row = connection.execute(select(orders).where(orders.c.out_trade_no == out_trade_no)).mappings().first()
        if not row:
            return False
        _lock_user(connection, row["user_id"])
        current = connection.execute(select(orders.c.status).where(orders.c.out_trade_no == out_trade_no)).scalar()
        if current != "PAID":
            return False
        connection.execute(update(orders).where(orders.c.out_trade_no == out_trade_no).values(
            status="REFUNDED", refunded_at=_db_now(connection).isoformat(), started_at=None, expires_at=None))
        _recompute(connection, row["user_id"])
        return True


