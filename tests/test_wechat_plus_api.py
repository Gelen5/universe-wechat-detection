import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from server import database
from server import wechat_plus_api as api
from server import wechat_plus_repository as repo
from server.rate_limit import LimitResult


class PlusAPITests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
        self.patches = [patch.object(database, 'ENGINE', self.engine),
            patch.object(api.tasks, 'dispatch', return_value='task'),
            patch.object(api, 'check_agent_submission', return_value=LimitResult(True))]
        for item in self.patches:
            item.start()
        repo.init_schema()
        app = FastAPI()

        @app.middleware('http')
        async def auth(request, call_next):
            name = request.headers.get('X-Test-User')
            request.state.user = {'id':name} if name else None
            return await call_next(request)

        app.include_router(api.router)
        self.client = TestClient(app)
        self.headers = {'X-Test-User':'owner'}

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.engine.dispose()

    def test_owner_scope_refresh_idempotency_and_cancel(self):
        self.assertEqual(self.client.get('/api/wechat-plus/sessions').status_code, 401)
        row = self.client.post('/api/wechat-plus/sessions', json={'title':'邮件整理'}, headers=self.headers).json()['session']
        url = '/api/wechat-plus/sessions/' + row['id']
        self.assertEqual(self.client.get(url, headers={'X-Test-User':'other'}).status_code, 404)
        body = {'message':'帮我选题','version':1,'idempotency_key':'request-once'}
        first = self.client.post(url+'/messages', json=body, headers=self.headers)
        self.assertEqual(first.status_code, 202)
        replay = self.client.post(url+'/messages', json=body, headers=self.headers)
        self.assertEqual(first.json()['turn']['id'], replay.json()['turn']['id'])
        loaded = self.client.get(url, headers=self.headers).json()['session']
        self.assertEqual(loaded['turns'][0]['status'], 'queued')
        turn = loaded['turns'][0]['id']
        self.assertEqual(self.client.post(url+'/cancel/'+turn, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get(url, headers=self.headers).json()['session']['turns'][0]['status'], 'cancelled')
        self.assertEqual(self.client.post(url+'/messages', json=dict(body,message='   ',idempotency_key='blank-once'), headers=self.headers).status_code, 422)

    def test_edit_invalidates_preview_and_keeps_versions(self):
        row = repo.create('owner')
        state = {'messages':[], 'versions':[], 'article_state':api.service.runtime.initialize('改稿')}
        state['article_state'].update(draft='旧稿',formatted_output='/tmp/old.html')
        repo.save(row['id'], 'owner', 1, state)
        url = '/api/wechat-plus/sessions/' + row['id']
        response = self.client.put(url+'/draft', json={'version':2,'draft':'手动改稿'}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        current = response.json()['session']
        self.assertEqual(current['state']['article_state']['formatted_output'], '')
        self.assertEqual([v['draft'] for v in current['state']['versions']], ['旧稿','手动改稿'])
        self.assertEqual(self.client.put(url+'/draft', json={'version':2,'draft':'旧页面'}, headers=self.headers).status_code, 409)


if __name__ == '__main__':
    unittest.main()
