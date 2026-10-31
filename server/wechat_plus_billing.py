"""公众号创作 Plus 的按动作计费记录。

为什么单独一张表：Plus 的一条消息先落库（202 + Celery），积分是在 API 层预扣、
在执行完的那个 worker 里结算的。两边都要知道「这一 turn 对应哪笔预扣」，而
``wechat_plus_turns`` 已经在线上跑着，加列要写迁移；新建一张只放三列的小表更省事，
``create_all`` 就能建出来。

表是 append-only 的：一条 turn 一行，settled_at 只在结算/退款后回填一次。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select, update

from . import database

metadata = MetaData()
charges = Table(
    'wechat_plus_charges', metadata,
    Column('turn_id', String(32), primary_key=True),
    Column('usage_id', String(64), nullable=False, index=True),
    Column('action', String(24)),
    Column('points', Integer),
    Column('created_at', String(40), nullable=False),
    Column('settled_at', String(40)),
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_schema() -> None:
    metadata.create_all(database.ENGINE)


def attach(turn_id: str, usage_id: str) -> None:
    """把一次预扣挂到 turn 上；重复调用只会更新 usage_id（重试用）。"""
    with database.ENGINE.begin() as db:
        existing = db.execute(select(charges.c.turn_id).where(charges.c.turn_id == turn_id)).first()
        if existing:
            db.execute(update(charges).where(charges.c.turn_id == turn_id).values(
                usage_id=usage_id, action=None, points=None, settled_at=None))
            return
        db.execute(insert(charges).values(
            turn_id=turn_id, usage_id=usage_id, created_at=now()))


def usage_for(turn_id: str) -> str | None:
    with database.ENGINE.connect() as db:
        row = db.execute(select(charges.c.usage_id).where(charges.c.turn_id == turn_id)).first()
        return row[0] if row else None


def record(turn_id: str, action: str, points: int) -> None:
    """结算完成时记下这次是什么动作、实际扣了多少，供界面回显。"""
    with database.ENGINE.begin() as db:
        db.execute(update(charges).where(charges.c.turn_id == turn_id).values(
            action=action, points=int(points), settled_at=now()))


def points_by_turn(turn_ids: list[str]) -> dict[str, int]:
    if not turn_ids:
        return {}
    with database.ENGINE.connect() as db:
        rows = db.execute(
            select(charges.c.turn_id, charges.c.points)
            .where(charges.c.turn_id.in_(turn_ids), charges.c.settled_at.is_not(None))
        ).all()
        return {row[0]: int(row[1] or 0) for row in rows}
