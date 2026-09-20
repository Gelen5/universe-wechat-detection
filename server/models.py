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


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240), default="新对话")
    skill_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(16), default="auto")
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    __table_args__ = (
        CheckConstraint("mode IN ('auto','manual')", name="ck_conversations_mode"),
        CheckConstraint("status IN ('active','archived')", name="ck_conversations_status"),
        Index("idx_conversations_user_updated", "user_id", "updated_at"),
    )


class ConversationMessage(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','tool','system')", name="ck_messages_role"),
        Index("idx_messages_conversation_created", "conversation_id", "created_at", "id"),
    )


class AgentRun(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    trigger_message_id: Mapped[str] = mapped_column(String(64), ForeignKey("messages.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_points: Mapped[int] = mapped_column(Integer, default=0)
    provider_cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    usage_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_runs_user_idempotency"),
        CheckConstraint("status IN ('queued','running','waiting_input','completed','failed','cancelled')", name="ck_runs_status"),
        CheckConstraint("cost_points >= 0 AND provider_cost_micros >= 0", name="ck_runs_cost_nonnegative"),
        CheckConstraint("attempt >= 0", name="ck_runs_attempt_nonnegative"),
        Index("idx_runs_conversation_created", "conversation_id", "created_at"),
    )


class ToolCall(Base):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    tool_name: Mapped[str] = mapped_column(String(160), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    arguments_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_tool_calls_status"),
    )


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(240), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[dict] = mapped_column(JSON_TYPE, default=dict)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    storage_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)
    __table_args__ = (
        CheckConstraint("type IN ('article','outline','topic','image','report','html','markdown')", name="ck_artifacts_type"),
        CheckConstraint("version > 0", name="ck_artifacts_version"),
        UniqueConstraint("conversation_id", "type", "version", name="uq_artifact_conversation_type_version"),
        Index("idx_artifacts_conversation_updated", "conversation_id", "updated_at"),
    )


class ProviderCall(Base):
    __tablename__ = "provider_calls"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), index=True)
    model: Mapped[str] = mapped_column(String(160), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("tool_calls.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    __table_args__ = (
        CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND image_count >= 0 AND estimated_cost_micros >= 0", name="ck_provider_calls_nonnegative"),
    )
