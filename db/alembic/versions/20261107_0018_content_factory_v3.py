"""Add isolated V3 settings and audit tables; preserve existing commerce data."""
import sqlalchemy as sa
from alembic import op

revision = '20261107_0018'
down_revision = '20261107_0017'
branch_labels = None
depends_on = None


def upgrade():
    from server.content_factory_v3_store import metadata
    connection = op.get_bind()
    metadata.create_all(connection, checkfirst=True)
    inspector = sa.inspect(connection)
    additions = {
        'content_factory_v3_settings': {
            'vision_call_bound_micros': sa.Column(
                'vision_call_bound_micros', sa.Integer(), nullable=False, server_default='0'),
            'image_people_mode': sa.Column(
                'image_people_mode', sa.String(16), nullable=False, server_default='auto'),
        },
        'content_factory_v3_runs': {
            'attempt': sa.Column(
                'attempt', sa.Integer(), nullable=False, server_default='0'),
        },
    }
    for table_name, columns in additions.items():
        actual = {item['name'] for item in inspector.get_columns(table_name)}
        for column_name, column in columns.items():
            if column_name not in actual:
                op.add_column(table_name, column)


def downgrade():
    raise RuntimeError('Retain content factory audit records; use a forward migration.')
