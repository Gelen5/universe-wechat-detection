"""Add recharge referral ledger; no historical data rewriting or auto-activation."""
from alembic import op
revision='20261103_0012'
down_revision='20261031_0011'
branch_labels=None
depends_on=None

def upgrade():
    from server.referral_recharge import metadata
    from server.referrals import risk_table
    metadata.create_all(op.get_bind(),checkfirst=True)
    risk_table.create(op.get_bind(),checkfirst=True)

def downgrade():
    # Financial history is intentionally retained. Disable campaign and deploy a
    # forward fix; never roll back to legacy registration/task reward binaries.
    op.execute('UPDATE referral_campaign SET enabled=0 WHERE id=1')
