"""Create isolated agent attribution tables."""
from alembic import op
revision = '20261105_0014'
down_revision = '20261104_0013'
branch_labels = None
depends_on = None

def upgrade():
    from server.agent_schema import install
    install(op.get_bind())

def downgrade():
    raise RuntimeError('Agent attribution history must be retained; use a forward migration.')
