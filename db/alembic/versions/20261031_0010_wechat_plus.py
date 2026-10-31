"""Independent conversational WeChat Plus sessions and durable turns."""
from alembic import op
import sqlalchemy as sa

revision = '20261031_0010'
down_revision = '20261025_0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('wechat_plus_sessions',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('user_id', sa.String(64), nullable=False),
        sa.Column('title', sa.String(240), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('state', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False))
    op.create_index('ix_wechat_plus_sessions_user_id', 'wechat_plus_sessions', ['user_id'])
    op.create_table('wechat_plus_turns',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('session_id', sa.String(32), nullable=False),
        sa.Column('user_id', sa.String(64), nullable=False),
        sa.Column('idempotency_key', sa.String(120), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('task_id', sa.String(100)), sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.String(40), nullable=False),
        sa.Column('updated_at', sa.String(40), nullable=False),
        sa.Column('progress', sa.String(240), nullable=False),
        sa.Column('cache', sa.JSON()), sa.Column('input_version', sa.Integer(), nullable=False),
        sa.UniqueConstraint('session_id', 'idempotency_key', name='uq_wechat_plus_turn_key'))
    op.create_index('ix_wechat_plus_turns_session_id', 'wechat_plus_turns', ['session_id'])


def downgrade():
    op.drop_table('wechat_plus_turns')
    op.drop_table('wechat_plus_sessions')
