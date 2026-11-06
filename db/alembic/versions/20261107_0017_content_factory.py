"""Create exclusive content factory tables without touching legacy tables."""
from alembic import op

revision = "20261107_0017"
down_revision = "20261106_0016"
branch_labels = None
depends_on = None


def upgrade():
    from server.content_factory_purchase import metadata
    metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade():
    raise RuntimeError("Retain purchases and customer access; use a forward migration.")
