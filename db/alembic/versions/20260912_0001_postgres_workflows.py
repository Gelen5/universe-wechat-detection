"""Create legacy-compatible account tables and durable workflows."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260912_0001"
down_revision = None
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("display_name", sa.String(80), nullable=False), sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"), sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False), sa.Column("last_login_at", sa.Text()),
        sa.CheckConstraint("role IN ('user','admin')", name="ck_users_role"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_users_status"))
    op.create_table("wallets",
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("balance", sa.Integer(), nullable=False, server_default="0"), sa.Column("trial_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bonus_balance", sa.Integer(), nullable=False, server_default="0"), sa.Column("paid_balance", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("balance >= 0 AND trial_balance >= 0 AND bonus_balance >= 0 AND paid_balance >= 0", name="ck_wallet_nonnegative"))
    op.create_table("sessions",
        sa.Column("token_hash", sa.String(128), primary_key=True), sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("impersonator_id", sa.String(64), sa.ForeignKey("users.id")), sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False), sa.Column("last_seen_at", sa.Text(), nullable=False), sa.Column("revoked_at", sa.Text()))
    op.create_table("point_transactions",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False), sa.Column("balance_before", sa.Integer(), nullable=False), sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("bucket", sa.String(20), nullable=False), sa.Column("kind", sa.String(32), nullable=False), sa.Column("source", sa.String(32), nullable=False),
        sa.Column("feature", sa.Text()), sa.Column("request_id", sa.String(64)), sa.Column("operator_id", sa.String(64)), sa.Column("note", sa.Text()),
        sa.Column("allocation_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("created_at", sa.Text(), nullable=False))
    op.create_index("idx_point_transactions_user_time", "point_transactions", ["user_id", "created_at"])
    op.create_table("usage_records",
        sa.Column("request_id", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method", sa.String(12), nullable=False), sa.Column("path", sa.Text(), nullable=False), sa.Column("feature", sa.Text(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False), sa.Column("status", sa.String(24), nullable=False), sa.Column("http_status", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()), sa.Column("estimated_cost_micros", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allocation_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("created_at", sa.Text(), nullable=False), sa.Column("finished_at", sa.Text()))
    op.create_index("idx_usage_records_user_time", "usage_records", ["user_id", "created_at"])
    op.create_table("pricing_rules",
        sa.Column("method", sa.String(12), primary_key=True), sa.Column("path", sa.Text(), primary_key=True), sa.Column("feature", sa.Text(), nullable=False),
        sa.Column("points", sa.Integer(), nullable=False), sa.Column("estimated_cost_micros", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"), sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("points >= 0", name="ck_pricing_points"))
    op.create_table("admin_actions",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("operator_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_user_id", sa.String(64), sa.ForeignKey("users.id")), sa.Column("action", sa.Text(), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=False, server_default="{}"), sa.Column("created_at", sa.Text(), nullable=False))
    op.create_table("provider_settings",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("text_api_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("image_api_key", sa.Text(), nullable=False, server_default=""), sa.Column("text_base_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("image_base_url", sa.Text(), nullable=False, server_default=""), sa.Column("text_model", sa.Text(), nullable=False, server_default=""),
        sa.Column("image_model", sa.Text(), nullable=False, server_default=""), sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("updated_by", sa.String(64), sa.ForeignKey("users.id")))
    op.create_table("workbench_sessions",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False), sa.Column("created_at", sa.Text(), nullable=False), sa.Column("updated_at", sa.Text(), nullable=False))
    op.create_index("idx_workbench_sessions_user_time", "workbench_sessions", ["user_id", "updated_at"])
    op.create_table("workbench_jobs",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False), sa.Column("session_id", sa.String(64), nullable=False), sa.Column("usage_id", sa.String(64)),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("error", sa.Text()), sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text()), sa.Column("finished_at", sa.Text()), sa.UniqueConstraint("user_id", "idempotency_key"))
    op.create_table("jobs",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(40), nullable=False), sa.Column("lane", sa.String(20), nullable=False), sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("usage_id", sa.String(64)), sa.Column("status", sa.String(24), nullable=False, server_default="queued"), sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text()), sa.Column("error", sa.Text()), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False), sa.Column("started_at", sa.Text()), sa.Column("finished_at", sa.Text()), sa.Column("canceled_at", sa.Text()),
        sa.UniqueConstraint("user_id", "idempotency_key"))
    op.create_table("conversation_locks", sa.Column("id", sa.Text(), primary_key=True), sa.Column("token", sa.Text(), nullable=False), sa.Column("expires_at", sa.Text(), nullable=False))

    op.create_table("workflow_sessions",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False), sa.Column("mode", sa.String(20), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_node", sa.String(32), nullable=False), sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("input_json", JSON, nullable=False), sa.Column("state_json", JSON, nullable=False), sa.Column("usage_id", sa.String(64)),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("user_id", "idempotency_key", name="uq_workflow_user_idempotency"),
        sa.CheckConstraint("mode IN ('auto','interactive')", name="ck_workflow_mode"))
    op.create_table("workflow_nodes",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("workflow_id", sa.String(64), sa.ForeignKey("workflow_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_name", sa.String(32), nullable=False), sa.Column("attempt", sa.Integer(), nullable=False), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(180), nullable=False, unique=True), sa.Column("celery_task_id", sa.String(80)),
        sa.Column("input_json", JSON, nullable=False), sa.Column("result_json", JSON, nullable=False), sa.Column("error", sa.Text()),
        sa.Column("queued_at", sa.DateTime(timezone=True)), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("workflow_id", "node_name", "attempt", name="uq_workflow_node_attempt"))
    op.create_table("workflow_decisions",
        sa.Column("id", sa.String(64), primary_key=True), sa.Column("workflow_id", sa.String(64), sa.ForeignKey("workflow_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_name", sa.String(32), nullable=False), sa.Column("actor", sa.String(16), nullable=False), sa.Column("expected_version", sa.Integer(), nullable=False),
        sa.Column("decision_json", JSON, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("workflow_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("workflow_id", sa.String(64), sa.ForeignKey("workflow_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("node_name", sa.String(32)), sa.Column("payload_json", JSON, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("idx_workflow_events_replay", "workflow_events", ["workflow_id", "id"])


def downgrade():
    for name in ("workflow_events", "workflow_decisions", "workflow_nodes", "workflow_sessions", "conversation_locks", "jobs", "workbench_jobs", "workbench_sessions", "provider_settings", "admin_actions", "pricing_rules", "usage_records", "point_transactions", "sessions", "wallets", "users"):
        op.drop_table(name)
