"""Atomic, exclusive purchase primitives for the content factory.

Purchase, wallet update and ledger entry share one database transaction.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, Integer, LargeBinary, MetaData, String, Table, Text, select, update

from .models import PointTransaction, Wallet


metadata = MetaData()
products = Table(
    "content_factory_products", metadata,
    Column("id", String(64), primary_key=True),
    Column("status", String(20), nullable=False),
    Column("price_points", Integer, nullable=False),
    Column("buyer_id", String(64)),
    Column("sold_at", Text),
    Column("product_type", String(20), nullable=False, server_default="article"),
    Column("title", Text, nullable=False, server_default=""),
    Column("track", Text, nullable=False, server_default=""),
    Column("preview", Text, nullable=False, server_default=""),
    Column("content", Text, nullable=False, server_default=""),
    Column("image_data", LargeBinary),
    Column("image_type", String(50)),
    Column("preview_image", LargeBinary),
    Column("source_id", String(64), nullable=False, server_default=""),
    Column("source_title", Text, nullable=False, server_default=""),
    Column("source_url", Text, nullable=False, server_default=""),
    Column("source_date", String(32), nullable=False, server_default=""),
    Column("source_metrics", Text, nullable=False, server_default="{}"),
    Column("created_at", Text, nullable=False, server_default=""),
    Column("published_at", Text),
    Column("content_fingerprint", String(64), unique=True),
    CheckConstraint("price_points > 0", name="ck_content_factory_positive_price"),
    CheckConstraint("(status = 'sold' AND buyer_id IS NOT NULL) OR (status <> 'sold' AND buyer_id IS NULL)", name="ck_content_factory_sold_buyer"),
)

feedback = Table(
    "content_factory_feedback", metadata,
    Column("id", String(64), primary_key=True),
    Column("product_id", String(64), nullable=False),
    Column("user_id", String(64), nullable=False),
    Column("body", Text, nullable=False),
    Column("created_at", Text, nullable=False),
)

jobs = Table(
    "content_factory_jobs", metadata,
    Column("id", String(64), primary_key=True),
    Column("product_id", String(64), nullable=False),
    Column("angle", Text, nullable=False),
    Column("status", String(20), nullable=False),
    Column("error", Text),
    Column("created_at", Text, nullable=False),
    Column("lease_token", String(64)),
    Column("lease_until", Text),
)


class PurchaseError(Exception):
    pass


class SoldOut(PurchaseError):
    pass


class InsufficientPoints(PurchaseError):
    pass


def purchase(engine, product_id: str, user_id: str) -> dict:
    """Atomically assign one product and debit its buyer once.

    The conditional update serializes competing buyers across database
    processes. All subsequent writes occur in the same database transaction.
    """
    now = datetime.now(timezone.utc).isoformat()
    with engine.begin() as connection:
        claimed = connection.execute(
            update(products)
            .where(products.c.id == product_id, products.c.status == "published", products.c.buyer_id.is_(None))
            .values(status="sold", buyer_id=user_id, sold_at=now)
        )
        row = connection.execute(select(products.c.status, products.c.buyer_id, products.c.price_points)
                                 .where(products.c.id == product_id)).mappings().first()
        if claimed.rowcount != 1:
            if row and row["status"] == "sold" and row["buyer_id"] == user_id:
                return {"status": "purchased", "already_owned": True}
            raise SoldOut("商品不可购买或已售出")
        price = row["price_points"]
        if price <= 0:
            raise PurchaseError("商品价格无效")
        wallet = connection.execute(
            select(Wallet.__table__).where(Wallet.user_id == user_id).with_for_update()
        ).mappings().first()
        if not wallet or wallet["balance"] < price:
            raise InsufficientPoints("积分不足")
        allocation = {}
        balances = {}
        remaining = price
        for bucket in ("trial", "bonus", "paid"):
            balance = wallet[f"{bucket}_balance"]
            used = min(balance, remaining)
            balances[f"{bucket}_balance"] = balance - used
            if used:
                allocation[bucket] = used
                remaining -= used
        if remaining:
            raise PurchaseError("钱包积分分桶不一致")
        connection.execute(update(Wallet.__table__).where(Wallet.user_id == user_id).values(
            balance=wallet["balance"] - price, updated_at=now, **balances))
        connection.execute(PointTransaction.__table__.insert().values(
            id=uuid.uuid4().hex, user_id=user_id, amount=-price,
            balance_before=wallet["balance"], balance_after=wallet["balance"] - price,
            bucket="mixed", kind="consume", source="content_factory", feature="爆款成品买断",
            request_id=product_id, note="独家买断", allocation_json=json.dumps(allocation), created_at=now))
        return {"status": "purchased", "already_owned": False}
