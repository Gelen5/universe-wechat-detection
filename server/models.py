"""SQLAlchemy 2 models for durable creator workflows."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index,
    Integer, String, Table, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# The account service remains a legacy-compatible facade during migration. This
# declaration resolves workflow foreign keys without replacing that service.
users_table = Table(
    "users", Base.metadata,
    Column("id", String(64), primary_key=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("display_name", String(80), nullable=False),
    Column("password_hash", Text, nullable=False),
    Column("role", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", Text, nullable=False),
    Column("last_login_at", Text),
)


class WorkflowSession(Base):
    __tablename__ = "workflow_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(120))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    current_node: Mapped[str] = mapped_column(String(32), default="intent")
    version: Mapped[int] = mapped_column(Integer, default=1)
    input_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    state_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    usage_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_workflow_user_idempotency"),
        CheckConstraint("mode IN ('auto','interactive')", name="ck_workflow_mode"),
    )


class WorkflowNode(Base):
    __tablename__ = "workflow_nodes"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_sessions.id", ondelete="CASCADE"), index=True)
    node_name: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("workflow_id", "node_name", "attempt", name="uq_workflow_node_attempt"),
        Index("idx_workflow_nodes_claim", "status", "queued_at"),
    )


class WorkflowDecision(Base):
    __tablename__ = "workflow_decisions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_sessions.id", ondelete="CASCADE"), index=True)
    node_name: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(16))
    expected_version: Mapped[int] = mapped_column(Integer)
    decision_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (CheckConstraint("actor IN ('user','auto','system')", name="ck_workflow_decision_actor"),)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(String(64), ForeignKey("workflow_sessions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    node_name: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (Index("idx_workflow_events_replay", "workflow_id", "id"),)
