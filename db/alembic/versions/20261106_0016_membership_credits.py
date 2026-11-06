"""Add durable membership credit installment and refund ledgers."""
from alembic import op

revision = '20261106_0016'
down_revision = '20261105_0015'
branch_labels = None
depends_on = None


def upgrade():
    from server.viral_insights_membership import credit_campaign, credit_grants, credit_refunds
    connection = op.get_bind()
    for table in (credit_campaign, credit_grants, credit_refunds):
        table.create(connection, checkfirst=True)


def downgrade():
    # Financial ledgers are retained for audit and safe replay.
    pass
