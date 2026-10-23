"""Store the stage a Run actually executed.

Stage routing moved from the browser (keyword rules) to a model call, so the
resolved stage has to be durable: failure messages, retries and analytics all
need it. Nullable for rows created before this revision.
"""
from alembic import op
import sqlalchemy as sa


revision = "20261023_0008"
down_revision = "20260921_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("runs", sa.Column("stage", sa.String(24), nullable=True))


def downgrade():
    op.drop_column("runs", "stage")
