import unittest, uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests import support
from server.main import app
from server import behavior_analytics as analytics
from server import accounts
from sqlalchemy import select, func
from server.rate_limit import LimitResult

class BehaviorTests(unittest.TestCase):
 def setUp(self):
  self.client=TestClient(app)
  limiter=patch.object(analytics,'check_behavior_observation',return_value=LimitResult(True))
  limiter.start()
  self.addCleanup(limiter.stop)
 def login(self):
  self.client.post('/api/auth/register',json={'email':f'{uuid.uuid4().hex}@example.com','password':'testing-pass-123','display_name':'test'})
 def test_collection_rejects_unknown_values_and_ignores_sensitive_fields(self):
  visitor=uuid.uuid4().hex
  self.login()
  payload={'visitor':visitor,'page':'viral-remix','event':'page_view','seconds':0,'device':'mobile','body':'secret prompt'}
  self.assertEqual(self.client.post('/api/behavior',json=payload).status_code,204)
  payload['page']='secret-prompt'
  self.assertEqual(self.client.post('/api/behavior',json=payload).status_code,422)
  with analytics.database.ENGINE.connect() as db:
   row=db.execute(select(analytics.events).where(analytics.events.c.visitor==visitor)).mappings().one()
   self.assertNotIn('body',row)
 def test_guest_events_are_collected_and_separated_in_owner_report(self):
  visitor=uuid.uuid4().hex
  payload={'visitor':visitor,'page':'image-board','event':'page_view','seconds':0,'device':'mobile'}
  self.assertEqual(self.client.post('/api/behavior',json=payload).status_code,204)
  payload.update(page='sticker-extract',event='sticker_extract')
  self.assertEqual(self.client.post('/api/behavior',json=payload).status_code,204)
  with analytics.database.ENGINE.connect() as db:
   rows=db.execute(select(analytics.events).where(analytics.events.c.visitor==visitor)).mappings().all()
  self.assertEqual(len(rows),2)
  self.assertTrue(all(row['user_id'] is None for row in rows))
  self.login()
  with patch.object(accounts,'require_admin',return_value={'email':'gelen5@163.com','role':'admin'}):
   report=self.client.get('/api/owner-behavior?days=7').json()
  self.assertGreaterEqual(report['summary']['guest_sessions'],1)
  self.assertTrue(any(row['page']=='image-board' and row['guest_sessions'] >= 1 for row in report['pages']))
  self.assertTrue(any(row['event']=='sticker_extract' and row['guest_sessions'] >= 1 for row in report['actions']))
 def test_report_and_html_are_owner_only(self):
  self.assertIn(self.client.get('/owner-behavior').status_code,(401,403))
  self.assertIn(self.client.get('/api/owner-behavior').status_code,(401,403))
  self.login()
  with patch.object(accounts,'require_admin',return_value={'email':'someone@example.com','role':'admin'}):
   self.assertEqual(self.client.get('/api/owner-behavior').status_code,403)
  with patch.object(accounts,'require_admin',return_value={'email':'gelen5@163.com','role':'admin','impersonation':{'active':True}}):
   self.assertEqual(self.client.get('/api/owner-behavior').status_code,403)
  with patch.object(accounts,'require_admin',return_value={'email':'gelen5@163.com','role':'admin'}):
   self.assertEqual(self.client.get('/owner-behavior').status_code,200)
   self.assertEqual(self.client.get('/api/owner-behavior?days=7').status_code,200)
   self.assertEqual(self.client.get('/api/owner-behavior?days=300').status_code,422)
