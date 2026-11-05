"""Independent manually confirmed agent transfers; no payment or wallet mutation."""
from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, MetaData, String, Table, Text, UniqueConstraint
metadata=MetaData()
Table('agent_profiles',metadata,Column('user_id',String(64),primary_key=True))
settlements=Table('agent_settlements',metadata,
    Column('id',String(64),primary_key=True),
    Column('request_key',String(64),nullable=False,unique=True),
    Column('agent_id',String(64),ForeignKey('agent_profiles.user_id'),nullable=False),
    Column('amount_cents',Integer,nullable=False),
    Column('operator_id',String(64),nullable=False),
    Column('note',Text,nullable=False),
    Column('transfer_ref',String(120),nullable=False),
    UniqueConstraint('agent_id','transfer_ref',name='uq_agent_transfer_ref'),
    Column('created_at',Text,nullable=False),
    CheckConstraint('amount_cents > 0',name='ck_agent_settlement_positive'))
Index('ix_agent_settlements_agent',settlements.c.agent_id)

def install(bind):
    metadata.create_all(bind,tables=[settlements],checkfirst=True)

if __name__=='__main__':
    from .database import ENGINE
    with ENGINE.begin() as conn: install(conn)
