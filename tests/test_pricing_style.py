"""The payment pages must use the app's own palette.

/pay and /pricing used to be a standalone blue page (#1677ff) that looked like a
different product. These tests pin the shared light-green glass tokens so a later
edit cannot quietly fall back to the old look.
"""
import re
import unittest

from tests import support  # noqa: F401 - isolated account database
from server.main import app
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


if __name__ == '__main__':
    unittest.main()

