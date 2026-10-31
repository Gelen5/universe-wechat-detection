"""账单页（/bill）：站长专属权限、入口、渲染与 CSV 导出。"""
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests import support  # noqa: F401 - 配置隔离数据库，必须在 app 之前导入
from server import accounts
from server.main import app

OWNER_EMAIL = accounts.OWNER_EMAIL
OWNER_PASSWORD = 'testing-pass-123'


class BillPageTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def _owner_client(self):
        """站长账号（support 里 CREATOR_OWNER_EMAIL=admin@example.com）。"""
        client = TestClient(app)
        login = client.post('/api/auth/login', json={
            'email': OWNER_EMAIL, 'password': OWNER_PASSWORD,
        })
        self.assertEqual(200, login.status_code, login.text)
        return client, login.json()['user']

    def _register(self, email):
        response = self.client.post('/api/auth/register', json={
            'email': email, 'password': 'testing-pass-123', 'display_name': '账单测试',
        })
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_anonymous_user_is_asked_to_log_in(self):
        response = self.client.get('/bill')
        self.assertEqual(401, response.status_code)
        self.assertIn('请先登录', response.text)

    def test_anonymous_export_is_rejected(self):
        response = self.client.get('/api/bill/export.csv')
        self.assertEqual(401, response.status_code)

    def test_ordinary_user_is_forbidden_even_with_a_direct_url(self):
        """入口隐藏只是 UI；直接访问 /bill 也必须被拦下来。"""
        self._register(f'bill-outsider-{id(self)}@example.com')
        response = self.client.get('/bill')
        self.assertEqual(403, response.status_code, response.text)
        self.assertIn('无权访问', response.text)
        # 不能泄露任何经营数据
        self.assertNotIn('REVENUE', response.text)
        self.assertNotIn('净收入', response.text)

    def test_ordinary_user_cannot_export_csv(self):
        self._register(f'bill-outsider-csv-{id(self)}@example.com')
        response = self.client.get('/api/bill/export.csv')
        self.assertEqual(403, response.status_code)

    def test_owner_sees_the_page_and_revenue_card(self):
        client, user = self._owner_client()
        response = client.get('/bill')
        self.assertEqual(200, response.status_code, response.text)
        self.assertIn('我的账单', response.text)
        self.assertIn('REVENUE', response.text)

    def test_owner_can_export_csv_with_bom(self):
        client, _ = self._owner_client()
        response = client.get('/api/bill/export.csv')
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        text = response.content.decode('utf-8-sig')
        self.assertIn('时间,类型,说明,状态,金额/积分,积分桶,订单号', text)
        self.assertIn('attachment; filename="bill.csv"', response.headers['content-disposition'])

    def test_owner_sees_consumption_records(self):
        client, owner = self._owner_client()
        accounts.recharge(owner['id'], owner['id'], 50, 'bonus', '账单测试赠送')
        accounts.reserve_points(
            owner['id'], {'feature': '账单测试功能', 'points': 5}, 'POST', '/api/bill-probe',
        )
        response = client.get('/bill')
        self.assertEqual(200, response.status_code)
        self.assertIn('账单测试功能', response.text)

    def test_refunded_request_shows_as_refund_row(self):
        """失败的扣费要出现在账单里并被标成退回，否则用户看不出钱去哪了。"""
        client, owner = self._owner_client()
        accounts.recharge(owner['id'], owner['id'], 50, 'paid', '账单测试充值')
        request_id = accounts.reserve_points(
            owner['id'], {'feature': '会失败的请求', 'points': 5}, 'POST', '/api/bill-probe',
        )
        accounts.refund_usage(request_id, 500, 800)
        response = client.get('/bill')
        self.assertEqual(200, response.status_code)
        self.assertIn('会失败的请求', response.text)
        self.assertIn('已退回', response.text)
        # 退款行的内部键不外泄
        self.assertNotIn(':refund', response.text)


class BillEntryTests(unittest.TestCase):
    """账单入口只对站长可见，且挂在账号菜单「我的积分」下面。"""

    static = Path(__file__).resolve().parents[1] / 'static'

    def test_account_menu_has_bill_right_after_wallet_and_hidden(self):
        html = (self.static / 'index.html').read_text(encoding='utf-8')
        wallet_at = html.index('id="wallet-settings-button"')
        bill_at = html.index('id="bill-settings-button"')
        logout_at = html.index('id="logout-button"')
        self.assertLess(wallet_at, bill_at)
        self.assertLess(bill_at, logout_at)
        block = html[bill_at:bill_at + 200]
        self.assertIn('>账单</button>', block)
        # 默认隐藏，由 app.js 按站长身份解开
        self.assertIn('hidden', block)

    def test_menu_click_navigates_to_the_bill_page(self):
        script = (self.static / 'app.js').read_text(encoding='utf-8')
        self.assertIn("document.querySelector('#bill-settings-button')", script)
        self.assertIn("window.location.href = '/bill'", script)

    def test_visibility_is_gated_by_owner_not_plain_login(self):
        script = (self.static / 'app.js').read_text(encoding='utf-8')
        self.assertIn('billSettingsButton.hidden = !isAdmin', script)

    def test_sidebar_popover_gates_bill_behind_owner_check(self):
        script = (self.static / 'sidebar.js').read_text(encoding='utf-8')
        self.assertIn('href="/bill" hidden', script)
        self.assertIn("gelen5@163.com", script)

    def test_bill_is_not_registered_as_a_sidebar_route(self):
        # 独立服务端页面：不注册 view、也不进 APP_NAV，否则 SPA 会清空内容区变白屏。
        self.assertNotIn('/bill', (self.static / 'routes.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
