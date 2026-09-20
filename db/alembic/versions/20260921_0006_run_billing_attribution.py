"""Attribute usage and cost records to normalized Agent Runs."""
from alembic import op
import sqlalchemy as sa


revision = "20260921_0006"
down_revision = "20260921_0005"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in (
        ("conversation_id", sa.String(64)), ("run_id", sa.String(64)),
        ("skill_id", sa.String(120)), ("tool_call_id", sa.String(64)),
        ("provider", sa.String(80)), ("model", sa.String(160)),
    ):
        op.add_column("usage_records", sa.Column(name, kind, nullable=True))
    op.add_column("usage_records", sa.Column(
        "actual_cost_micros", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_index("ix_usage_records_conversation_id", "usage_records", ["conversation_id"])
    op.create_index("ix_usage_records_skill_id", "usage_records", ["skill_id"])
    op.create_index("uq_usage_records_run_id", "usage_records", ["run_id"], unique=True)


def downgrade():
    op.drop_index("uq_usage_records_run_id", table_name="usage_records")
    op.drop_index("ix_usage_records_skill_id", table_name="usage_records")
    op.drop_index("ix_usage_records_conversation_id", table_name="usage_records")
    for name in ("actual_cost_micros", "model", "provider", "tool_call_id",
                 "skill_id", "run_id", "conversation_id"):
        op.drop_column("usage_records", name)
