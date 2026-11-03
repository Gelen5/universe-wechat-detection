"""Create isolated viral insights trial and membership orders."""
from alembic import op

revision = "20261104_0013"
down_revision = "20261103_0012"
branch_labels = None
depends_on = None


def upgrade():
    from server.viral_insights_membership import metadata
    metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade():
    # Retain trial/payment history. Rollback application code without dropping ledger data.
    pass
