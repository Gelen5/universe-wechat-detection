"""Owner-only activity analytics. No article bodies, credentials or prompt storage."""
from datetime import datetime, timedelta, timezone, date
import uuid
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import MetaData, Table, Column, String, Text, Index, text
from . import accounts, database

TZ = timezone(timedelta(hours=8))
meta = MetaData()
events = Table('user_activity_events', meta,
    Column('id', String(64), primary_key=True), Column('user_id', String(64), nullable=False),
    Column('kind', String(20), nullable=False), Column('created_at', Text, nullable=False))
Index('ix_activity_user_time', events.c.user_id, events.c.created_at)
Index('ix_activity_time', events.c.created_at)

def init_db():
    meta.create_all(database.ENGINE)
    with database.ENGINE.begin() as c:
        c.execute(text("CREATE TABLE IF NOT EXISTS analytics_meta (key VARCHAR(64) PRIMARY KEY, value TEXT NOT NULL)"))
        c.execute(text("INSERT INTO analytics_meta(key,value) VALUES ('activity_started',:now) ON CONFLICT(key) DO NOTHING"), {'now': accounts.utc_now()})

def record(user, kind='active'):
    # Analytics must never turn a successful login into a failed login.
    try:
        _record(user, kind)
    except Exception:
        import logging
        logging.getLogger(__name__).warning('Activity observation unavailable; kind=%s', kind)

def _record(user, kind='active'):
    if not user or user.get('impersonation'):
        return
    now = datetime.now(timezone.utc)
    with accounts.DB_LOCK, accounts._connect() as c:
        # At most one activity observation per user per minute, across web workers.
        identity = uuid.uuid4().hex if kind == 'login' else f"{user['id']}:{int(now.timestamp()) // 60}"
        import hashlib
        identity = hashlib.sha256(identity.encode()).hexdigest()
        c.execute("INSERT INTO user_activity_events(id,user_id,kind,created_at) VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING",
                  (identity, user['id'], kind, now.isoformat()))
        if kind == 'login':
            c.execute('UPDATE users SET last_login_at=? WHERE id=?', (now.isoformat(), user['id']))

def stamp(value):
    if not value: return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError: return None

def session_logins():
    """Recover only actual Better Auth session creation times, never task times."""
    from sqlalchemy import inspect
    if not inspect(database.ENGINE).has_table('auth_session'):
        return {}
    with database.ENGINE.connect() as c:
        rows=c.execute(text('SELECT "userId", MAX("createdAt") FROM auth_session GROUP BY "userId"')).all()
    return {row[0]: stamp(row[1]).isoformat() for row in rows if stamp(row[1])}

def enrich_logins(users):
    logins=session_logins()
    for user in users:
        observed=logins.get(user['id'])
        if observed and (not stamp(user['last_login_at']) or stamp(observed)>stamp(user['last_login_at'])):
            user['last_login_at']=observed
            user['login_source']='认证会话创建记录'
    return users

def period(start, end):
    try:
        first = date.fromisoformat(start) if start else datetime.now(TZ).date()
        last = date.fromisoformat(end) if end else first
    except ValueError: raise HTTPException(422, '日期格式应为 YYYY-MM-DD')
    if last < first or (last-first).days > 90: raise HTTPException(422, '请选择不超过 91 天的日期范围')
    return datetime.combine(first, datetime.min.time(), TZ), datetime.combine(last+timedelta(days=1), datetime.min.time(), TZ)

router = APIRouter()
@router.post('/api/activity')
def activity(request: Request):
    user = accounts.require_user(request)
    record(user)
    return {'status':'success'}

@router.get('/api/admin/activity')
def report(request: Request, start: str='', end: str='', query: str='', metric: str='all', role: str='user', feature: str='', user_id: str='', page: int=1, view: str='users', sort: str='active'):
    accounts.require_admin(request)
    if role not in ('all','user','admin') or metric not in ('all','new','active','creators','tasks','failed'): raise HTTPException(422,'筛选无效')
    if view not in ('users','tasks') or sort not in ('active','new','tasks') or len(query)>254: raise HTTPException(422,'筛选无效')
    lower, upper = period(start,end)
    def inside(value):
        d=stamp(value)
        return d is not None and lower <= d < upper
    with accounts._connect() as c:
        users=[dict(r) for r in c.execute('SELECT u.id,u.email,u.display_name,u.role,u.status,u.created_at,u.last_login_at,w.balance FROM users u JOIN wallets w ON u.id=w.user_id').fetchall()]
        ev=[dict(r) for r in c.execute('SELECT user_id,kind,created_at FROM user_activity_events WHERE created_at>=? AND created_at<?', (lower.astimezone(timezone.utc).isoformat(),upper.astimezone(timezone.utc).isoformat())).fetchall()]
        latest={r['user_id']:r['latest'] for r in c.execute('SELECT user_id,MAX(created_at) AS latest FROM user_activity_events GROUP BY user_id').fetchall()}
        usages=[dict(r) for r in c.execute('SELECT * FROM usage_records WHERE created_at>=? AND created_at<?', (lower.astimezone(timezone.utc).isoformat(),upper.astimezone(timezone.utc).isoformat())).fetchall()]
        jobs=[dict(r) for r in c.execute('SELECT id,user_id,type,lane,usage_id,status,error,attempts,created_at,started_at,finished_at FROM jobs WHERE created_at>=? AND created_at<?',(lower.astimezone(timezone.utc).isoformat(),upper.astimezone(timezone.utc).isoformat())).fetchall()]
        wb=[dict(r) for r in c.execute('SELECT id,user_id,usage_id,status,error,created_at,started_at,finished_at FROM workbench_jobs WHERE created_at>=? AND created_at<?',(lower.astimezone(timezone.utc).isoformat(),upper.astimezone(timezone.utc).isoformat())).fetchall()]
        started=c.execute("SELECT value FROM analytics_meta WHERE key='activity_started'").fetchone()[0]
    users=enrich_logins(users)
    by_id={u['id']:u for u in users}
    linked={j['usage_id']:j for j in jobs+wb if j.get('usage_id')}
    tasks=[]
    for r in usages:
        j=linked.get(r['request_id'],{})
        tasks.append(dict(id=j.get('id',r['request_id']), user_id=r['user_id'], feature=r['feature'], status=j.get('status',r['status']), created_at=r['created_at'],started_at=j.get('started_at'),finished_at=j.get('finished_at',r['finished_at']),duration_ms=None if j else r['duration_ms'],points=r['points'],billing_status=r['status'],error=j.get('error'),attempts=j.get('attempts'),conversation_id=r.get('conversation_id')))
    usage_ids={r['request_id'] for r in usages}
    for j in jobs+wb:
        if j.get('usage_id') in usage_ids: continue
        tasks.append(dict(id=j['id'],user_id=j['user_id'],feature=j.get('type','公众号创作'),status=j['status'],created_at=j['created_at'],started_at=j.get('started_at'),finished_at=j.get('finished_at'),duration_ms=None,points=None,billing_status='unknown',error=j.get('error'),attempts=j.get('attempts')))
    allowed={u['id'] for u in users if (role=='all' or u['role']==role) and (not user_id or u['id']==user_id) and (not query or query.lower() in (u['email']+' '+u['display_name']).lower())}
    job_ids={j['id'] for j in jobs}
    for task in tasks:
        task['refundable']=task['id'] in job_ids and task['status'] in ('queued','running')
    tasks=[t for t in tasks if t['user_id'] in allowed and (not feature or t['feature']==feature)]
    creators={t['user_id'] for t in tasks}
    if feature: allowed &= creators
    active={e['user_id'] for e in ev if inside(e['created_at'])} & allowed
    new={u['id'] for u in users if u['id'] in allowed and inside(u['created_at'])}
    failed=lambda t: t['status'] in ('failed','refunded','error')
    summary={'new':len(new),'active':len(active),'creators':len(creators),'tasks':len(tasks),'failed':sum(failed(t) for t in tasks),'total':len(allowed)}
    trend=[]
    day=lower
    while day<upper:
        key=day.date().isoformat()
        trend.append({'date':key,'new':sum(u['id'] in allowed and stamp(u['created_at']).astimezone(TZ).date()==day.date() for u in users if stamp(u['created_at'])),'active':len({e['user_id'] for e in ev if e['user_id'] in allowed and stamp(e['created_at']).astimezone(TZ).date()==day.date()})})
        day+=timedelta(days=1)
    features={}
    for t in tasks: features[t['feature']]=features.get(t['feature'],0)+1
    if view=='tasks':
        selected={'new':new,'active':active,'creators':creators}.get(metric,allowed)
        tasks=[t for t in tasks if t['user_id'] in selected]
        rows=[dict(t,email=by_id[t['user_id']]['email'],display_name=by_id[t['user_id']]['display_name']) for t in tasks if metric!='failed' or failed(t)]
        rows.sort(key=lambda t:t['created_at'],reverse=True)
    else:
        selected={'new':new,'active':active,'creators':creators,'tasks':creators,'failed':{t['user_id'] for t in tasks if failed(t)}}.get(metric,allowed)
        rows=[]
        for u in users:
            if u['id'] not in allowed & selected: continue
            own=[t for t in tasks if t['user_id']==u['id']]
            rows.append(dict(u,last_active_at=latest.get(u['id']),task_count=len(own),failed_tasks=sum(failed(t) for t in own)))
        rows.sort(key=lambda u:(u['created_at'] if sort=='new' else u['task_count'] if sort=='tasks' else u.get('last_active_at') or ''),reverse=True)
    import re
    for row in rows:
        if row.get('error'):
            row['error']=re.sub(r'(?:sk-|re_)[A-Za-z0-9_-]+', '[REDACTED]', str(row['error']))[:2000]
    page=max(1,page); total=len(rows)
    return {'summary':summary,'trend':trend,'features':features,'rows':rows[(page-1)*25:page*25],'total':total,'page':page,'page_size':25,'activity_started':started,'updated_at':accounts.utc_now()}

@router.get('/api/admin/activity/users/{user_id}')
def detail(user_id: str, request: Request):
    accounts.require_admin(request)
    result=enrich_logins([accounts.admin_user_detail(user_id)])[0]
    with accounts._connect() as c:
        result['activity']=[dict(r) for r in c.execute('SELECT kind,created_at FROM user_activity_events WHERE user_id=? ORDER BY created_at DESC LIMIT 50',(user_id,)).fetchall()]
        result['transactions']=[dict(r) for r in c.execute('SELECT amount,balance_before,balance_after,bucket,kind,feature,note,created_at FROM point_transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 50',(user_id,)).fetchall()]
    from sqlalchemy import inspect
    inspector=inspect(database.ENGINE)
    result['email_verified']=None
    if inspector.has_table('auth_user'):
        cols={c['name'] for c in inspector.get_columns('auth_user')}
        field=next((name for name in ('emailVerified','email_verified') if name in cols),None)
        if field:
            with database.ENGINE.connect() as c:
                row=c.execute(text(f'SELECT "{field}" FROM auth_user WHERE id=:id'),{'id':user_id}).first()
                if row is not None: result['email_verified']=bool(row[0])
    return result
