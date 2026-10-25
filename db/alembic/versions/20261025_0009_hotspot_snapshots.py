"""Hourly hotspot snapshots for the 热点广场 tab.

The live list only ever shows "now" (Redis, 15 minute TTL). Ranking movement,
how long a topic stayed on the board and cross-platform frequency all need
history, so one row per topic per hour is kept and pruned after 30 days.
"""
from alembic import op
import sqlalchemy as sa


revision = "20261025_0009"
down_revision = "20261023_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hotspot_snapshots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("hot", sa.String(64), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_hotspot_snapshots_platform", "hotspot_snapshots", ["platform"])
    op.create_index("ix_hotspot_snapshots_captured_at", "hotspot_snapshots", ["captured_at"])
    op.create_index("idx_hotspot_platform_captured", "hotspot_snapshots",
                    ["platform", "captured_at"])


def downgrade():
    op.drop_index("idx_hotspot_platform_captured", table_name="hotspot_snapshots")
    op.drop_index("ix_hotspot_snapshots_captured_at", table_name="hotspot_snapshots")
    op.drop_index("ix_hotspot_snapshots_platform", table_name="hotspot_snapshots")
    op.drop_table("hotspot_snapshots")
