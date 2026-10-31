import unittest
import uuid

from tests import support  # noqa: F401 - isolated account database
from server.main import app
from fastapi.testclient import TestClient


class PayPageNavTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        email = f"pay-nav-{uuid.uuid4().hex[:8]}@example.com"
        self.client.post('/api/auth/register', json={
            'email': email, 'password': 'testing-pass-123', 'display_name': 'pay'})

    def _html(self, path):
        response = self.client.get(path)
        self.assertEqual(200, response.status_code)
        return response.text

    def test_custom_amount_checkout_offers_a_way_back(self):
        html = self._html('/pay')
        self.assertIn('href="/pricing"', html)
        self.assertIn('返回积分套餐', html)
        self.assertIn('返回工作台', html)

    def test_package_checkout_offers_a_way_back(self):
        html = self._html('/pay?package=pro')
        self.assertIn('换一个套餐', html)
        self.assertIn('返回工作台', html)


if __name__ == '__main__':
    unittest.main()
