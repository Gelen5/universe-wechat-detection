"""Add durable execution leases to normalized Runs."""
from alembic import op
import sqlalchemy as sa


revision = "20260920_0003"
down_revision = "20260920_0002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("celery_task_id", sa.String(80)))
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True)))
        batch.create_check_constraint("ck_runs_attempt_nonnegative", "attempt >= 0")
    op.create_index("ix_runs_celery_task_id", "runs", ["celery_task_id"])
    op.create_index("ix_runs_heartbeat_at", "runs", ["heartbeat_at"])


def downgrade():
    op.drop_index("ix_runs_heartbeat_at", table_name="runs")
    op.drop_index("ix_runs_celery_task_id", table_name="runs")
    with op.batch_alter_table("runs") as batch:
        batch.drop_constraint("ck_runs_attempt_nonnegative", type_="check")
        batch.drop_column("heartbeat_at")
        batch.drop_column("attempt")
        batch.drop_column("celery_task_id")
