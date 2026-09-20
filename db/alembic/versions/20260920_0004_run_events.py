"""Add durable normalized Run event log for resumable SSE."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260920_0004"
down_revision = "20260920_0003"
branch_labels = None
depends_on = None
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade():
    op.create_table("run_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(64), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False), sa.Column("payload_json", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("idx_run_events_replay", "run_events", ["run_id", "id"])
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])
    op.create_index("ix_run_events_conversation_id", "run_events", ["conversation_id"])
    op.create_index("ix_run_events_user_id", "run_events", ["user_id"])
    op.create_index("ix_run_events_event_type", "run_events", ["event_type"])


def downgrade():
    op.drop_table("run_events")
