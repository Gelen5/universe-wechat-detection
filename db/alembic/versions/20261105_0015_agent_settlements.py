"""Independent manual agent transfer records."""
from alembic import op
revision='20261105_0015'
down_revision='20261105_0014'
branch_labels=None
depends_on=None

def upgrade():
    from server.agent_settlement_schema import install
    install(op.get_bind())

def downgrade():
    raise RuntimeError('Retain financial history; use a forward migration.')
