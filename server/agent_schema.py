"""Additive agent tables shared by the migration and targeted installer."""
from sqlalchemy import Boolean, CheckConstraint, Column, ForeignKey, Index, MetaData, String, Table, Text

metadata = MetaData()
# Referenced legacy users table is declared for FK resolution and is never created here.
users = Table('users', metadata, Column('id', String(64), primary_key=True))
profiles = Table('agent_profiles', metadata,
    Column('user_id', String(64), ForeignKey('users.id'), primary_key=True),
    Column('code', String(32), nullable=False, unique=True),
    Column('active', Boolean, nullable=False, server_default='true'),
    Column('created_at', Text, nullable=False))
customers = Table('agent_customers', metadata,
    Column('customer_id', String(64), ForeignKey('users.id'), primary_key=True),
    Column('agent_id', String(64), ForeignKey('agent_profiles.user_id'), nullable=False),
    Column('created_at', Text, nullable=False),
    CheckConstraint('customer_id <> agent_id', name='ck_agent_not_self'))
Index('ix_agent_customers_agent', customers.c.agent_id)


def install(bind):
    # Never create or change legacy tables, and preserve the existing alembic marker.
    metadata.create_all(bind, tables=[profiles, customers], checkfirst=True)

if __name__ == '__main__':
    from .database import ENGINE
    with ENGINE.begin() as connection:
        install(connection)
