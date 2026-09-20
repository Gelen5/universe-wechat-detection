"""Add idempotent source keys for Tool-produced Artifacts."""
from alembic import op
import sqlalchemy as sa


revision = "20260921_0007"
down_revision = "20260921_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("artifacts", sa.Column("source_key", sa.String(220), nullable=True))
    op.create_index("uq_artifacts_source_key", "artifacts", ["source_key"], unique=True)


def downgrade():
    op.drop_index("uq_artifacts_source_key", table_name="artifacts")
    op.drop_column("artifacts", "source_key")
