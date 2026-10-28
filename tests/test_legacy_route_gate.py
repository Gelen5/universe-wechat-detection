"""The legacy workbench gate: observe first, then refuse, never charge.

The gate exists so the superseded ``/api/workbench/*`` and ``/api/workflows/*``
routes can be retired from evidence instead of assumption: production logs show
whether any client still calls them, and flipping to ``gone`` refuses the calls
without reserving points.
"""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from tests import support  # noqa: F401 - isolated account database
from server import legacy_routes
from server.main import app


class LegacyRouteGateTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        response = self.client.post('/api/auth/register', json={
            'email': f'gate-{id(self)}@example.com',
            'password': 'testing-pass-123',
            'display_name': 'gate',
        })
        self.assertEqual(200, response.status_code, response.text)

    def _post(self, path, payload=None):
        return self.client.post(path, json=payload or {})

    def test_default_mode_keeps_legacy_routes_open(self):
        with patch.dict('os.environ', {}, clear=False):
            import os
            os.environ.pop('LEGACY_WORKBENCH_MODE', None)
            self.assertEqual('open', legacy_routes.mode())
            response = self._post('/api/workbench/cancel', {'session_id': 'x', 'step': 1})
        self.assertNotEqual(410, response.status_code)

    def test_gone_mode_refuses_workbench_and_workflow_routes(self):
        with patch.dict('os.environ', {'LEGACY_WORKBENCH_MODE': 'gone'}):
            for path, payload in (
                ('/api/workbench/sessions', {'topic': 'x', 'mode': 'interactive'}),
                ('/api/workbench/steps', {'session_id': 'x', 'step': 2}),
                ('/api/workflows', {'topic': 'x', 'mode': 'interactive'}),
            ):
                with self.subTest(path=path):
                    response = self._post(path, payload)
                    self.assertEqual(410, response.status_code, response.text)

    def test_blocked_call_reserves_no_points(self):
        before = self.client.get('/api/wallet').json()['wallet']['balance']
        with patch.dict('os.environ', {'LEGACY_WORKBENCH_MODE': 'gone'}):
            # /api/workbench/sessions costs 30 points when it is served.
            self._post('/api/workbench/sessions', {'topic': 'x', 'mode': 'interactive'})
        after = self.client.get('/api/wallet').json()['wallet']['balance']
        self.assertEqual(before, after)

    def test_gate_does_not_touch_other_product_routes(self):
        with patch.dict('os.environ', {'LEGACY_WORKBENCH_MODE': 'gone'}):
            self.assertNotEqual(410, self.client.get('/api/pricing').status_code)
            self.assertNotEqual(410, self.client.get('/api/conversations').status_code)

    def test_blocked_call_still_requires_login(self):
        with patch.dict('os.environ', {'LEGACY_WORKBENCH_MODE': 'gone'}):
            anonymous = TestClient(app)
            response = anonymous.post('/api/workbench/cancel', json={'session_id': 'x', 'step': 1})
        self.assertEqual(401, response.status_code)

    def test_unknown_mode_falls_back_to_open(self):
        with patch.dict('os.environ', {'LEGACY_WORKBENCH_MODE': 'GONE? '}):
            self.assertEqual('open', legacy_routes.mode())

    def test_matches_only_legacy_prefixes(self):
        self.assertTrue(legacy_routes.matches('/api/workflows'))
        self.assertTrue(legacy_routes.matches('/api/workflows/abc/events'))
        self.assertTrue(legacy_routes.matches('/api/workbench/sessions'))
        self.assertFalse(legacy_routes.matches('/api/conversations'))
        self.assertFalse(legacy_routes.matches('/api/workbenchx'))
        self.assertFalse(legacy_routes.matches('/api/qihaoshou/generate'))


if __name__ == '__main__':
    unittest.main()
