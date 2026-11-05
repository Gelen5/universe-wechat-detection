"""The payment pages must use the app's own palette.

/pay and /pricing used to be a standalone blue page (#1677ff) that looked like a
different product. These tests pin the shared light-green glass tokens so a later
edit cannot quietly fall back to the old look.
"""
import re
import unittest
import uuid
from unittest.mock import patch

from tests import support  # noqa: F401 - isolated account database
from server.main import app
from server import alipay_pay
from sqlalchemy import insert
from fastapi.testclient import TestClient

BLUE = re.compile(r'#1677ff|rgba\(22,\s*119,\s*255|#eef2ff', re.I)
GREEN_TOKENS = ['#1B7A58', '#0F5132', 'rgba(150,214,182', '--lg-fill', 'backdrop-filter']


class PricingStyleTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _page(self, path):
        response = self.client.get(path)
        self.assertEqual(200, response.status_code, response.text[:200])
        return response.text

    def test_pricing_page_uses_the_green_glass_palette(self):
        html = self._page('/pricing')
        for token in GREEN_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, html)
        self.assertNotRegex(html, BLUE)

    def test_pay_page_shares_the_same_palette(self):
        html = self._page('/pay')
        for token in GREEN_TOKENS:
            with self.subTest(token=token):
                self.assertIn(token, html)
        self.assertNotRegex(html, BLUE)

    def test_package_cards_keep_their_links_and_prices(self):
        html = self._page('/pricing')
        for package in ('starter', 'pro', 'master'):
            self.assertIn(f'/pay?package={package}', html)
        self.assertIn('plan-cta', html)
        self.assertIn('¥', html)

    def test_pages_still_render_without_login(self):
        for path in ('/pricing', '/pay'):
            with self.subTest(path=path):
                self.assertEqual(200, self.client.get(path).status_code)

    def test_packages_and_checkout_use_same_price_and_credits(self):
        expected = {'starter': ('19.90', 159), 'pro': ('49.90', 499),
                    'master': ('99.90', 999)}
        packages = self.client.get('/api/pay/packages').json()['packages']
        self.assertEqual({p['id']: (p['price'], p['credits']) for p in packages}, expected)
        self.client.post('/api/auth/register', json={'email': f'{uuid.uuid4().hex}@example.com',
            'password': 'testing-pass-123', 'display_name': 'test'})
        with patch.object(alipay_pay, 'load_payment_config', return_value={'app_id': 'test'}), \
             patch.object(alipay_pay, '_page_pay_form', return_value='<form></form>'):
            for package_id, (price, credits) in expected.items():
                result = self.client.post('/api/pay/alipay/orders', json={'package_id': package_id,
                    'total_amount': '0.01'}).json()
                self.assertEqual((result['total_amount'], result['credits']), (price, credits))
                row = alipay_pay._recharge_for(result['out_trade_no'])
                self.assertEqual((row['amount'], row['credits']), (price, credits))

    def test_pricing_displays_image_estimates_and_caveat(self):
        html = self._page('/pricing')
        for count in ('79', '249', '499'):
            self.assertIn(f'<strong>{count}<small> 张</small></strong>', html)
        self.assertIn('159 积分', html)
        self.assertNotIn('所有套餐均按 1 元 = 10 积分到账', html)
        self.assertIn('不同图片功能消耗可能不同', html)
        self.assertIn('拆解、策划和文案', html)

    def test_old_order_uses_recorded_credits_after_package_changes(self):
        order_id = uuid.uuid4().hex
        with alipay_pay.ENGINE.begin() as db:
            db.execute(insert(alipay_pay.alipay_recharges).values(out_trade_no=order_id,
                user_id='existing-user', package_id='starter', credits=199, amount='19.90',
                status='PENDING', created_at=alipay_pay._now()))
        with patch.object(alipay_pay.accounts, 'credit_alipay_recharge', return_value={'credited': True}) as credit:
            alipay_pay._credit_recharge(order_id)
            self.assertEqual(credit.call_args.args[1], 199)
            alipay_pay._credit_recharge(order_id)
            credit.assert_called_once()


if __name__ == '__main__':
    unittest.main()

