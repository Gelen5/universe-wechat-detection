from fastapi.testclient import TestClient
from tests import support
from server.main import app

def test_wish_routes_are_removed_without_removing_plus():
 client=TestClient(app)
 assert client.get('/wish-square').status_code==404
 assert client.get('/admin/wishes').status_code==404
 html=client.get('/').text
 assert 'wish-square-frame' not in html
 assert 'wish-admin-badge' not in html
 assert client.get('/wechat-plus').status_code==200

def test_old_writing_pages_redirect_to_plus_and_preserve_topic():
 client=TestClient(app,follow_redirects=False)
 for path in ('/workbench?topic=hello','/one-click-writing?topic=hello','/qihaoshou?topic=hello'):
  response=client.get(path)
  assert response.status_code==307
  assert response.headers['location']=='/wechat-plus?topic=hello'

def test_legacy_write_is_stopped_before_billing():
 from uuid import uuid4
 client=TestClient(app)
 client.post('/api/auth/register',json={'email':uuid4().hex+'@example.com','password':'testing-pass-123','display_name':'test'})
 before=client.get('/api/wallet').json()
 for path in ('/api/workbench/chat','/api/qihaoshou/generate'):
  response=client.post(path,json={})
  assert response.status_code==410
 assert client.get('/api/wallet').json()==before
