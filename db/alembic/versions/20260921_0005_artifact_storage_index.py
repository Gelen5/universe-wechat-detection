"""Index artifact object-storage keys for owner-scoped retrieval."""
from alembic import op


revision = "20260921_0005"
down_revision = "20260920_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_artifacts_storage_key", "artifacts", ["storage_key"])


def downgrade():
    op.drop_index("ix_artifacts_storage_key", table_name="artifacts")
