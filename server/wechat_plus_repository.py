"""Persistent, owner-scoped Plus conversations with optimistic concurrency."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import MetaData, Table, Column, String, Integer, Text, JSON, UniqueConstraint, select, insert, update
from . import database

metadata = MetaData()
sessions = Table('wechat_plus_sessions', metadata,
    Column('id', String(32), primary_key=True), Column('user_id', String(64), nullable=False, index=True),
    Column('title', String(240), nullable=False), Column('version', Integer, nullable=False),
    Column('state', JSON, nullable=False), Column('updated_at', String(40), nullable=False))
turns = Table('wechat_plus_turns', metadata,
    Column('id', String(32), primary_key=True), Column('session_id', String(32), nullable=False,index=True),
    Column('user_id', String(64), nullable=False), Column('idempotency_key', String(120), nullable=False),
    Column('status', String(24), nullable=False), Column('message', Text, nullable=False),
    Column('task_id', String(100)), Column('error', Text), Column('created_at', String(40),nullable=False),
    Column('updated_at', String(40), nullable=False), Column('progress', String(240), nullable=False),
    Column('cache', JSON), Column('input_version', Integer, nullable=False),
    UniqueConstraint('session_id', 'idempotency_key', name='uq_wechat_plus_turn_key'))

class Conflict(ValueError):
    pass

def now():
    return datetime.now(timezone.utc).isoformat()

def init_schema():
    metadata.create_all(database.ENGINE)

def create(user_id: str, title='新创作'):
    row={'id':uuid.uuid4().hex,'user_id':user_id,'title':title[:240],'version':1,
         'state':{'messages':[],'article_state':None,'choices':[],'versions':[]},'updated_at':now()}
    with database.ENGINE.begin() as db:
        db.execute(insert(sessions).values(**row))
    return row

def get(session_id,user_id):
    with database.ENGINE.connect() as db:
        row=db.execute(select(sessions).where(sessions.c.id==session_id,sessions.c.user_id==user_id)).mappings().first()
        if not row: raise KeyError('创作不存在或不属于当前用户')
        result=dict(row)
        result['turns']=[{k:v for k,v in t.items() if k != 'cache'} for t in db.execute(select(turns).where(turns.c.session_id==session_id,turns.c.user_id==user_id).order_by(turns.c.created_at.desc()).limit(20)).mappings()]
        return result

def list_sessions(user_id):
    with database.ENGINE.connect() as db:
        return [dict(r) for r in db.execute(select(sessions.c.id,sessions.c.title,sessions.c.version,sessions.c.updated_at).where(sessions.c.user_id==user_id).order_by(sessions.c.updated_at.desc()).limit(50)).mappings()]

def save(session_id,user_id,version,state):
    with database.ENGINE.begin() as db:
        changed=db.execute(update(sessions).where(sessions.c.id==session_id,sessions.c.user_id==user_id,sessions.c.version==version).values(state=state,version=version+1,updated_at=now())).rowcount
        if changed!=1: raise Conflict('内容已更新，请读取最新版本后重试')
    return get(session_id,user_id)

def enqueue(session_id,user_id,version,message,key):
    with database.ENGINE.begin() as db:
        # Serialize submissions for a single conversation in PostgreSQL.
        row=db.execute(select(sessions).where(sessions.c.id==session_id,sessions.c.user_id==user_id).with_for_update()).mappings().first()
        if not row: raise KeyError('创作不存在')
        existing=db.execute(select(turns).where(turns.c.session_id==session_id,turns.c.idempotency_key==key)).mappings().first()
        if existing:return dict(existing),False
        if row['version']!=version:raise Conflict('会话已更新，请刷新后提交')
        active=db.execute(select(turns.c.id).where(turns.c.session_id==session_id,turns.c.status.in_(['queued','running']))).first()
        if active:raise Conflict('当前操作仍在执行，请等待或取消')
        turn={'id':uuid.uuid4().hex,'session_id':session_id,'user_id':user_id,'idempotency_key':key,'status':'queued','message':message,'created_at':now(),'updated_at':now(),'progress':'等待执行','cache':{},'input_version':version}
        db.execute(insert(turns).values(**turn))
        return turn,True

def claim(turn_id,task_id):
    with database.ENGINE.begin() as db:
        changed=db.execute(update(turns).where(turns.c.id==turn_id,turns.c.status=='queued').values(status='running',task_id=task_id,updated_at=now(),progress='正在理解你的要求')).rowcount
        if changed!=1:return None
        return dict(db.execute(select(turns).where(turns.c.id==turn_id)).mappings().one())

def finish(turn_id,task_id,status,error=''):
    if status not in {'completed','failed','cancelled'}:raise ValueError('无效任务状态')
    with database.ENGINE.begin() as db:
        return db.execute(update(turns).where(turns.c.id==turn_id,turns.c.task_id==task_id,turns.c.status=='running').values(status=status,error=error[:1000],updated_at=now())).rowcount==1

def cancel(turn_id,user_id):
    with database.ENGINE.begin() as db:
        return db.execute(update(turns).where(turns.c.id==turn_id,turns.c.user_id==user_id,turns.c.status.in_(['queued','running'])).values(status='cancelled',updated_at=now())).rowcount==1


def commit_turn(turn_id, task_id, version, state):
    """Publish a result only while its claim and input version are still valid.

    Cancellation and result publication serialize on the same turn row. A late
    provider response can therefore never resurrect a cancelled operation.
    """
    with database.ENGINE.begin() as db:
        turn = db.execute(select(turns).where(turns.c.id == turn_id)
                          .with_for_update()).mappings().first()
        if not turn or turn['status'] != 'running' or turn['task_id'] != task_id:
            return False
        changed = db.execute(update(sessions).where(
            sessions.c.id == turn['session_id'],
            sessions.c.user_id == turn['user_id'],
            sessions.c.version == version).values(
                state=state, version=version + 1, updated_at=now())).rowcount
        if changed != 1:
            raise Conflict('文章已经更新，本次结果未覆盖新内容')
        db.execute(update(turns).where(turns.c.id == turn_id).values(
            status='completed', error='', updated_at=now(), progress='完成'))
        return True


def is_running(turn_id, task_id):
    with database.ENGINE.connect() as db:
        return db.execute(select(turns.c.id).where(
            turns.c.id == turn_id, turns.c.task_id == task_id,
            turns.c.status == 'running')).first() is not None


def heartbeat(turn_id, task_id, progress=None):
    values = {'updated_at': now()}
    if progress is not None:
        values['progress'] = progress[:240]
    with database.ENGINE.begin() as db:
        return db.execute(update(turns).where(turns.c.id == turn_id,
            turns.c.task_id == task_id, turns.c.status == 'running').values(**values)).rowcount == 1


def recover():
    """Outbox reconciliation and expired worker claims; live workers renew leases."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=180)).isoformat()
    with database.ENGINE.begin() as db:
        db.execute(update(turns).where(turns.c.status == 'running',
            turns.c.updated_at < cutoff).values(status='queued', task_id=None,
                progress='执行中断，正在恢复', updated_at=now()))
        return list(db.execute(select(turns.c.id).where(turns.c.status == 'queued')).scalars())


def cache_result(turn_id, task_id, key, result):
    with database.ENGINE.begin() as db:
        turn = db.execute(select(turns).where(turns.c.id == turn_id).with_for_update()).mappings().first()
        if not turn or turn['status'] != 'running' or turn['task_id'] != task_id:
            return False
        cache = dict(turn['cache'] or {})
        cache[key] = result
        db.execute(update(turns).where(turns.c.id == turn_id).values(cache=cache, updated_at=now()))
        return True


def retry(session_id, turn_id, user_id):
    with database.ENGINE.begin() as db:
        session = db.execute(select(sessions).where(sessions.c.id == session_id,
            sessions.c.user_id == user_id).with_for_update()).mappings().first()
        if not session:
            raise KeyError('创作不存在')
        turn = db.execute(select(turns).where(turns.c.id == turn_id,
            turns.c.session_id == session_id, turns.c.user_id == user_id).with_for_update()).mappings().first()
        if not turn:
            raise KeyError('操作不存在')
        if turn['status'] != 'failed':
            raise Conflict('只能重试未完成的失败操作')
        if session['version'] != turn['input_version']:
            raise Conflict('内容已更新，请基于当前内容重新提出要求')
        if db.execute(select(turns.c.id).where(turns.c.session_id == session_id,
            turns.c.status.in_(['queued', 'running']))).first():
            raise Conflict('当前操作仍在执行')
        db.execute(update(turns).where(turns.c.id == turn_id).values(
            status='queued', task_id=None, error='', progress='正在恢复上次处理', updated_at=now()))
        return dict(db.execute(select(turns).where(turns.c.id == turn_id)).mappings().one())
