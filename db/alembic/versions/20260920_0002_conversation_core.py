"""Add normalized conversation, run, tool, artifact and provider-call models."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260920_0002"
down_revision = "20260912_0001"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table("conversations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(240), nullable=False, server_default="新对话"),
        sa.Column("skill_id", sa.String(120)), sa.Column("mode", sa.String(16), nullable=False, server_default="auto"),
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("metadata_json", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mode IN ('auto','manual')", name="ck_conversations_mode"),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_conversations_status"))
    op.create_index("idx_conversations_user_updated", "conversations", ["user_id", "updated_at"])
    op.create_index("ix_conversations_skill_id", "conversations", ["skill_id"])
    op.create_index("ix_conversations_status", "conversations", ["status"])
    op.create_table("messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("conversation_id", sa.String(64), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False), sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_json", JSON, nullable=False), sa.Column("metadata_json", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user','assistant','tool','system')", name="ck_messages_role"))
    op.create_index("idx_messages_conversation_created", "messages", ["conversation_id", "created_at", "id"])
    op.create_table("runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("conversation_id", sa.String(64), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("trigger_message_id", sa.String(64), sa.ForeignKey("messages.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", sa.String(120)), sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("error_code", sa.String(80)), sa.Column("error_message", sa.Text()),
        sa.Column("cost_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_cost_micros", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("usage_id", sa.String(64)), sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_runs_user_idempotency"),
        sa.CheckConstraint("status IN ('queued','running','waiting_input','completed','failed','cancelled')", name="ck_runs_status"),
        sa.CheckConstraint("cost_points >= 0 AND provider_cost_micros >= 0", name="ck_runs_cost_nonnegative"))
    op.create_index("idx_runs_conversation_created", "runs", ["conversation_id", "created_at"])
    op.create_index("ix_runs_trigger_message_id", "runs", ["trigger_message_id"])
    op.create_index("ix_runs_user_id", "runs", ["user_id"])
    op.create_index("ix_runs_skill_id", "runs", ["skill_id"])
    op.create_index("ix_runs_status", "runs", ["status"])
    op.create_index("ix_runs_usage_id", "runs", ["usage_id"])
    op.create_table("tool_calls",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", sa.String(120)), sa.Column("tool_name", sa.String(160), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False, unique=True),
        sa.Column("arguments_json", JSON, nullable=False), sa.Column("result_json", JSON, nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.CheckConstraint("status IN ('queued','running','completed','failed','cancelled')", name="ck_tool_calls_status"))
    op.create_index("ix_tool_calls_run_id", "tool_calls", ["run_id"])
    op.create_index("ix_tool_calls_tool_name", "tool_calls", ["tool_name"])
    op.create_index("ix_tool_calls_status", "tool_calls", ["status"])
    op.create_table("artifacts",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(64), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(32), nullable=False), sa.Column("title", sa.String(240), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""), sa.Column("content_json", JSON, nullable=False),
        sa.Column("storage_key", sa.String(500)), sa.Column("storage_url", sa.Text()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("type IN ('article','outline','topic','image','report','html','markdown')", name="ck_artifacts_type"),
        sa.CheckConstraint("version > 0", name="ck_artifacts_version"),
        sa.UniqueConstraint("conversation_id", "type", "version", name="uq_artifact_conversation_type_version"))
    op.create_index("idx_artifacts_conversation_updated", "artifacts", ["conversation_id", "updated_at"])
    op.create_index("ix_artifacts_user_id", "artifacts", ["user_id"])
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])
    op.create_index("ix_artifacts_type", "artifacts", ["type"])
    op.create_table("provider_calls",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model", sa.String(160), nullable=False), sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"), sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer()), sa.Column("estimated_cost_micros", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_call_id", sa.String(64), sa.ForeignKey("tool_calls.id", ondelete="SET NULL")),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("input_tokens >= 0 AND output_tokens >= 0 AND image_count >= 0 AND estimated_cost_micros >= 0", name="ck_provider_calls_nonnegative"))
    for name, columns in (("ix_provider_calls_provider", ["provider"]), ("ix_provider_calls_model", ["model"]),
                          ("ix_provider_calls_run_id", ["run_id"]), ("ix_provider_calls_tool_call_id", ["tool_call_id"]),
                          ("ix_provider_calls_user_id", ["user_id"])):
        op.create_index(name, "provider_calls", columns)


def downgrade():
    for table in ("provider_calls", "artifacts", "tool_calls", "runs", "messages", "conversations"):
        op.drop_table(table)
