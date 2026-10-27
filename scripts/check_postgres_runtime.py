"""Exercise runtime transactions against PostgreSQL in a disposable schema.

Run inside the application environment: python scripts/check_postgres_runtime.py
Uses DATABASE_URL, creates a UUID-named schema, and drops only that schema.
Does not call providers or access customer tables in the public schema.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uuid, threading, concurrent.futures
from sqlalchemy import create_engine, text, select, func
from sqlalchemy.orm import sessionmaker
from server import database
from server.models import Base, Wallet, AgentRun, users_table
from server import conversation_repository as repository
original=database.ENGINE
if original.dialect.name != "postgresql":
    raise SystemExit("This isolated concurrency check requires PostgreSQL")
schema='release_check_'+uuid.uuid4().hex
with original.begin() as db: db.execute(text('CREATE SCHEMA '+schema))
engine=create_engine(original.url,connect_args={'options':'-c search_path='+schema+' -c statement_timeout=15000 -c lock_timeout=5000'},pool_size=10,max_overflow=0)
database.ENGINE=engine
database.SessionLocal=sessionmaker(bind=engine,expire_on_commit=False)
try:
    Base.metadata.create_all(engine)
    with engine.begin() as db:
        db.execute(users_table.insert(),dict(id='check-user',email='release@example.invalid',display_name='Release check',password_hash='disabled',role='user',status='active',created_at='2026-10-27'))
        db.execute(Wallet.__table__.insert(),dict(user_id='check-user',balance=1000,trial_balance=1000,bonus_balance=0,paid_balance=0,updated_at='2026-10-27'))
    conv=repository.create_conversation('check-user')
    def submit(_): return repository.create_message_run(conv['id'],'check-user','write','same-key',reserve_points=10)[1]['id']
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: ids=list(pool.map(submit,range(8)))
    assert len(set(ids))==1
    with database.session_scope() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun))==1
        assert db.get(Wallet,'check-user').balance==990
    first=repository.create_artifact(ids[0],'check-user','outline',content='Original outline')
    _,pinned,_=repository.create_message_run(conv['id'],'check-user','next','pinned-key',reserve_points=7)
    repository.create_artifact_version(first['id'],'check-user',content='Future outline')
    assert repository.run_inputs(pinned['id'],'check-user')['artifacts'][0]['content']=='Original outline'
    # Read the actual head, independent of list ordering.
    current=max(repository.list_artifacts(conv['id'],'check-user'),key=lambda a:a['version'])
    gate=threading.Barrier(2)
    def edit(i):
        gate.wait()
        try:
            repository.create_artifact_version(current['id'],'check-user',content='Editor '+str(i),expected_current_id=current['id'])
            return 'saved'
        except repository.ArtifactVersionConflict: return 'conflict'
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool: outcomes=list(pool.map(edit,range(2)))
    assert sorted(outcomes)==['conflict','saved'],outcomes
    for i in range(10):
        _,run,_=repository.create_message_run(conv['id'],'check-user','race','race-'+str(i),reserve_points=1)
        repository.claim_run(run['id'],'lease')
        gate=threading.Barrier(2)
        def write():
            gate.wait()
            try: repository.create_artifact(run['id'],'check-user','article',content='race output',task_id='lease')
            except RuntimeError: pass
        def cancel():
            gate.wait()
            repository.cancel_run(run['id'],'check-user')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            a,b=pool.submit(write),pool.submit(cancel)
            a.result(timeout=20);b.result(timeout=20)
        events=repository.events_after(run['id'],'check-user')
        cancelled=next(e['id'] for e in events if e['type']=='run.cancelled')
        assert all(e['id']<cancelled for e in events if e['type']=='artifact.created')
        try: repository.create_artifact(run['id'],'check-user','article',content='late',task_id='lease')
        except RuntimeError: pass
        else: raise AssertionError('Late write accepted after cancellation')
    for run_id in (ids[0],pinned['id']): repository.cancel_run(run_id,'check-user')
    with database.session_scope() as db: assert db.get(Wallet,'check-user').balance==1000
    print('PostgreSQL verified: 8 duplicate submissions charged once; fixed inputs; concurrent edit conflict; 10 cancel/write races; refunds balance restored')
finally:
    engine.dispose()
    assert schema.startswith('release_check_') and schema.isidentifier()
    with original.begin() as db: db.execute(text('DROP SCHEMA '+schema+' CASCADE'))
    print('Isolated PostgreSQL schema removed')
