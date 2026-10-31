import uuid
from datetime import datetime, timezone
from tests import support
from fastapi.testclient import TestClient
from server.main import app
from server import accounts, admin_activity


def clients():
    admin=TestClient(app)
    assert admin.post('/api/auth/login',json={'email':'admin@example.com','password':'testing-pass-123'}).status_code==200
    user=TestClient(app)
    data=user.post('/api/auth/register',json={'email':uuid.uuid4().hex+'@example.test','password':'testing-pass-123'}).json()
    return admin,user,data['user']

def test_permissions_and_no_poll_activity():
    a,u,who=clients()
    assert TestClient(app).get('/api/admin/activity').status_code==401
    assert u.get('/api/admin/activity').status_code==403
    with accounts._connect() as c:
        before=c.execute('SELECT COUNT(*) FROM user_activity_events WHERE user_id=?',(who['id'],)).fetchone()[0]
    u.get('/api/auth/me');u.get('/api/wallet')
    with accounts._connect() as c:
        assert c.execute('SELECT COUNT(*) FROM user_activity_events WHERE user_id=?',(who['id'],)).fetchone()[0]==before
    for _ in range(3): assert u.post('/api/activity').status_code==200
    d=a.get('/api/admin/activity',params={'user_id':who['id']}).json()
    assert d['summary']['active']==1
    assert d['rows'][0]['last_login_at']
    assert d['rows'][0]['last_active_at']
    detail=a.get('/api/admin/activity/users/'+who['id']).json()
    assert len(detail['activity'])==2 # login plus one deduplicated activity

def test_beijing_date_boundary_and_filters():
    a,u,who=clients()
    with accounts._connect() as c:
        c.execute('UPDATE users SET created_at=? WHERE id=?',('2026-10-30T16:01:00+00:00',who['id']))
    d=a.get('/api/admin/activity',params={'start':'2026-10-31','end':'2026-10-31','user_id':who['id'],'metric':'new'}).json()
    assert d['summary']['new']==1 and d['total']==1
    d=a.get('/api/admin/activity',params={'start':'2026-10-30','end':'2026-10-30','user_id':who['id'],'metric':'new'}).json()
    assert d['total']==0
    assert a.get('/api/admin/activity?start=bad').status_code==422
    assert a.get('/api/admin/activity?start=2020-01-01&end=2026-01-01').status_code==422

def test_jobs_deduplicated_and_failed_detail():
    a,u,who=clients()
    accounts.recharge(accounts.authenticate('admin@example.com','testing-pass-123')['id'],who['id'],20,'trial','fixture')
    usage=accounts.reserve_points(who['id'],{'feature':'贴图创作','points':1,'estimated_cost_micros':0},'POST','/fixture')
    job=accounts.create_job(who['id'],'tie_tu','light',uuid.uuid4().hex,usage,{})
    with accounts._connect() as c:
        c.execute('UPDATE jobs SET status=?,error=? WHERE id=?',('failed','provider sk-secretvalue failed',job['id']))
    d=a.get('/api/admin/activity',params={'user_id':who['id'],'view':'tasks','metric':'failed'}).json()
    assert d['summary']['tasks']==1 and d['summary']['failed']==1
    assert d['total']==1
    assert 'sk-secretvalue' not in d['rows'][0]['error']
    assert d['rows'][0]['billing_status']=='reserved' # not falsely refunded

def test_impersonation_is_not_user_activity():
    a,u,who=clients()
    with accounts._connect() as c:
        before=c.execute('SELECT count(*) FROM user_activity_events WHERE user_id=?',(who['id'],)).fetchone()[0]
    admin_activity.record(dict(who,impersonation={'active':True}))
    with accounts._connect() as c:
        assert c.execute('SELECT count(*) FROM user_activity_events WHERE user_id=?',(who['id'],)).fetchone()[0]==before
