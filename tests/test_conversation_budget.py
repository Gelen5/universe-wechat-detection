"""One creation is capped, not one message.

A finished article normally takes four or five messages, and each message used
to reserve the skill's base points, so the headline "10 积分" was really 40-70.
The cap bounds the whole conversation: once it is reached the remaining messages
of that creation cost nothing. Refunded runs (provider failures) must not eat
the budget.
"""
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests import support  # noqa: F401 - isolated account database
from server import conversation_repository
from server.main import app


def _register(client, suffix):
    response = client.post('/api/auth/register', json={
        'email': f'cap-{suffix}@example.com',
        'password': 'testing-pass-123', 'display_name': 'cap'})
    assert response.status_code == 200, response.text
    return response.json()['user']


class ConversationBudgetTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        suffix = id(self)
        self.user = _register(self.client, suffix)
        # Trial points are 0 in the test environment; fund the wallet directly.
        from server import database
        from server.models import Wallet
        with database.session_scope() as db:
            wallet = db.query(Wallet).filter(Wallet.user_id == self.user['id']).first()
            if wallet is None:
                wallet = Wallet(user_id=self.user['id'])
                db.add(wallet)
            wallet.balance = 200
            wallet.paid_balance = 200
        self.conversation = self.client.post('/api/conversations', json={
            'title': 'cap', 'skill_id': 'wechat_writer', 'mode': 'manual'}).json()['conversation']

    def _send(self, text='继续写', key=None):
        return self.client.post(
            f"/api/conversations/{self.conversation['id']}/messages",
            json={'content': text, 'content_json': {}},
            headers={'Idempotency-Key': key or f"cap-{id(self)}-{uuid.uuid4().hex[:8]}"},
        )

    def test_first_message_charges_the_base_price(self):
        with patch('server.conversation_api.dispatch_run'), patch('server.conversation_api.notify'):
            response = self._send('第一次')
        self.assertEqual(202, response.status_code, response.text)
        body = response.json()
        self.assertEqual(10, body['points_charged'])
        self.assertEqual(30, body['points_cap'])
        self.assertEqual(20, body['points_remaining'])

    def test_the_cap_ends_the_charging_for_this_creation(self):
        charges = []
        with patch('server.conversation_api.dispatch_run'), patch('server.conversation_api.notify'):
            for index in range(5):
                response = self._send(f'第{index}次')
                self.assertEqual(202, response.status_code, response.text)
                charges.append(response.json()['points_charged'])
        # 10 + 10 + 10 reaches the 30 cap; the last two messages are free.
        self.assertEqual([10, 10, 10, 0, 0], charges)
        self.assertEqual(30, conversation_repository.conversation_points_charged(
            self.conversation['id'], self.user['id']))

    def test_refunded_runs_do_not_consume_the_budget(self):
        with patch('server.conversation_api.dispatch_run'), patch('server.conversation_api.notify'):
            first = self._send('会被退款').json()
        from server import database
        from server.models import AgentRun
        with database.session_scope() as db:
            run = db.get(AgentRun, first['run_id'])
            conversation_repository._refund_usage_locked(db, run, 500)
        self.assertEqual(0, conversation_repository.conversation_points_charged(
            self.conversation['id'], self.user['id']))
        with patch('server.conversation_api.dispatch_run'), patch('server.conversation_api.notify'):
            again = self._send('重试').json()
        self.assertEqual(10, again['points_charged'])

    def test_conversation_endpoint_reports_the_budget(self):
        with patch('server.conversation_api.dispatch_run'), patch('server.conversation_api.notify'):
            self._send('一次')
        body = self.client.get(f"/api/conversations/{self.conversation['id']}").json()
        self.assertEqual(30, body['points_cap'])
        self.assertEqual(10, body['points_charged'])
        self.assertEqual(20, body['points_remaining'])


if __name__ == '__main__':
    unittest.main()
