from datetime import date
from unittest.mock import patch
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from tests import support
from server.main import app
from server import owner_revenue

def test_payment_time_and_refunds_are_separate():
 rows=[dict(out_trade_no='a',subject='创作包',total_amount='99.10',refunded_amount='19.20',status='PARTIAL_REFUNDED',paid_at='2026-10-31 23:59:00'),dict(out_trade_no='b',subject='体验包',total_amount='30.00',refunded_amount='0',status='PAID',paid_at='2026-11-01T00:01:00+08:00'),dict(out_trade_no='c',subject='其他',total_amount='500',refunded_amount='0',status='PENDING_PAYMENT',paid_at=None),dict(out_trade_no='d',subject='其他',total_amount='10',refunded_amount='0',status='PAID',paid_at=None)]
 d=owner_revenue.calculate(rows,date(2026,11,1),date(2026,11,1),date(2026,11,1))
 assert d['lifetime_paid']=='139.10' and d['lifetime_refunded']=='19.20' and d['lifetime_net']=='119.90'
 assert d['today_paid']=='30.00' and d['period_count']==1 and d['missing_paid_time']==1
 assert d['daily'][0]['amount']=='30.00' and len(d['orders'])==1

def test_owner_exact_email_and_impersonation():
 for u in ({'email':'other@example.com','role':'admin'},{'email':'gelen5@163.com','role':'admin','impersonation':{'active':True}}):
  with patch.object(owner_revenue.accounts,'require_admin',return_value=u):
   with pytest.raises(HTTPException) as e: owner_revenue.require_owner(None)
   assert e.value.status_code==403
 with patch.object(owner_revenue.accounts,'require_admin',return_value={'email':'Gelen5@163.com','role':'admin'}):
  assert owner_revenue.require_owner(None)['email']=='Gelen5@163.com'

def test_http_requires_user_and_owner():
 c=TestClient(app)
 assert c.get('/owner-revenue').status_code==401
 assert c.get('/api/owner-revenue').status_code==401
 with patch.object(owner_revenue.accounts,'require_admin',return_value={'email':'other@example.com','role':'admin'}):
  with pytest.raises(HTTPException):owner_revenue.require_owner(None)


def test_real_http_owner_and_other_user(monkeypatch):
 import uuid
 from server import accounts
 owner=TestClient(app)
 assert owner.post('/api/auth/login',json={'email':accounts.OWNER_EMAIL,'password':'testing-pass-123'}).status_code==200
 monkeypatch.setattr(owner_revenue,'OWNER',accounts.OWNER_EMAIL)
 assert owner.get('/owner-revenue').status_code==200
 result=owner.get('/api/owner-revenue?start=2026-10-31&end=2026-11-01')
 assert result.status_code==200 and len(result.json()['daily'])==2
 assert owner.get('/api/owner-revenue?start=2020-01-01&end=2026-01-01').status_code==422
 outsider=TestClient(app)
 assert outsider.post('/api/auth/register',json={'email':uuid.uuid4().hex+'@example.test','password':'testing-pass-123'}).status_code==200
 assert outsider.get('/owner-revenue').status_code==403
 assert outsider.get('/api/owner-revenue').status_code==403


def test_membership_payments_and_refunds_join_revenue_once(monkeypatch):
 import uuid
 from server import accounts, alipay_pay, database, viral_insights_membership as vim
 user=accounts.create_user(uuid.uuid4().hex+'@example.test','testing-pass-123','买家')
 key=uuid.uuid4().hex[:12]
 with database.ENGINE.begin() as conn:
  for suffix,status,refund in [('paid','PAID','0.00'),('refund','PARTIAL_REFUNDED','3.00'),('pending','CREATED','0.00')]:
   oid=key+suffix
   conn.execute(alipay_pay.alipay_orders.insert().values(out_trade_no=oid,app_id='test',subject='爆款情报会员·周卡',total_amount='9.90',status=status,refunded_amount=refund,created_at='2098-01-01 10:00:00',paid_at='2098-01-01 10:00:00' if suffix=='paid' else None,updated_at='2098-01-01 10:00:00'))
   conn.execute(vim.orders.insert().values(out_trade_no=oid,user_id=user['id'],package_id='week',amount='9.90',days=7,status='PAID' if status!='CREATED' else 'PENDING_PAYMENT',created_at='2098-01-01T02:00:00+00:00',paid_at='2098-01-01T02:00:00+00:00' if status!='CREATED' else None))
  # A malformed order associated with both products must not be counted twice.
  conn.execute(alipay_pay.alipay_recharges.insert().values(out_trade_no=key+'paid',user_id=user['id'],package_id='test',credits=1,amount='9.90',status='CREDITED',created_at='2098-01-01 10:00:00'))
 owner=TestClient(app)
 assert owner.post('/api/auth/login',json={'email':accounts.OWNER_EMAIL,'password':'testing-pass-123'}).status_code==200
 monkeypatch.setattr(owner_revenue,'OWNER',accounts.OWNER_EMAIL)
 data=owner.get('/api/owner-revenue?start=2098-01-01&end=2098-01-01').json()
 rows=[row for row in data['orders'] if row['out_trade_no'].startswith(key)]
 assert len(rows)==2 and data['period_paid']=='19.80' and data['period_count']==2
 assert sum(float(row['refunded_amount']) for row in rows)==3.0
 assert all(row['email']==user['email'] for row in rows)
