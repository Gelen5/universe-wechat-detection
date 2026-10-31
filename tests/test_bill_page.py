"""账单页（/bill）：入口、未登录、渲染、CSV 导出。"""
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from tests import support  # noqa: F401 - 配置隔离数据库，必须在 app 之前导入
from server import accounts
from server.main import app


class BillPageTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

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

    def test_page_renders_without_records(self):
        self._register(f'bill-empty-{id(self)}@example.com')
        response = self.client.get('/bill')
        self.assertEqual(200, response.status_code, response.text)
        self.assertIn('我的账单', response.text)
        self.assertIn('还没有账单记录', response.text)
        # 普通用户看不到站长收入卡
        self.assertNotIn('REVENUE', response.text)

    def test_consumption_record_persists_into_the_bill(self):
        user = self._register(f'bill-consume-{id(self)}@example.com')
        admin = next(u for u in accounts.list_users('admin@example.com') if u['email'] == 'admin@example.com')
        accounts.recharge(admin['id'], user['user']['id'], 50, 'bonus', '账单测试赠送')
        accounts.reserve_points(
            user['user']['id'], {'feature': '账单测试功能', 'points': 5}, 'POST', '/api/bill-probe',
        )
        response = self.client.get('/bill')
        self.assertEqual(200, response.status_code)
        self.assertIn('账单测试功能', response.text)

    def test_refunded_request_shows_as_refund_row(self):
        """失败的扣费要出现在账单里并被标成退回，否则用户看不出钱去哪了。"""
        user = self._register(f'bill-refund-{id(self)}@example.com')
        admin = next(u for u in accounts.list_users('admin@example.com') if u['email'] == 'admin@example.com')
        accounts.recharge(admin['id'], user['user']['id'], 50, 'paid', '账单测试充值')
        request_id = accounts.reserve_points(
            user['user']['id'], {'feature': '会失败的请求', 'points': 5}, 'POST', '/api/bill-probe',
        )
        accounts.refund_usage(request_id, 500, 800)
        response = self.client.get('/bill')
        self.assertEqual(200, response.status_code)
        self.assertIn('会失败的请求', response.text)
        self.assertIn('已退回', response.text)
        # 退款行的内部键不外泄
        self.assertNotIn(':refund', response.text)

    def test_csv_has_bom_and_header(self):
        self._register(f'bill-csv-{id(self)}@example.com')
        response = self.client.get('/api/bill/export.csv')
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.content.startswith(b'\xef\xbb\xbf'))
        text = response.content.decode('utf-8-sig')
        self.assertIn('时间,类型,说明,状态,金额/积分,积分桶,订单号', text)
        self.assertIn('attachment; filename="bill.csv"', response.headers['content-disposition'])


class BillEntryTests(unittest.TestCase):
    """账单入口挂在账号菜单「我的积分」下面，不是侧边栏一级菜单。"""

    static = Path(__file__).resolve().parents[1] / 'static'

    def test_account_menu_has_bill_right_after_wallet(self):
        html = (self.static / 'index.html').read_text(encoding='utf-8')
        wallet_at = html.index('id="wallet-settings-button"')
        bill_at = html.index('id="bill-settings-button"')
        logout_at = html.index('id="logout-button"')
        self.assertLess(wallet_at, bill_at)
        self.assertLess(bill_at, logout_at)
        self.assertIn('>账单</button>', html[bill_at:bill_at + 200])

    def test_menu_click_navigates_to_the_bill_page(self):
        script = (self.static / 'app.js').read_text(encoding='utf-8')
        self.assertIn("document.querySelector('#bill-settings-button')", script)
        self.assertIn("window.location.href = '/bill'", script)

    def test_sidebar_popover_on_page_less_shells_links_bill(self):
        script = (self.static / 'sidebar.js').read_text(encoding='utf-8')
        self.assertIn('<a role="menuitem" href="/bill">账单</a>', script)

    def test_bill_is_not_registered_as_a_sidebar_route(self):
        # 独立服务端页面：不注册 view、也不进 APP_NAV，否则 SPA 会清空内容区变白屏。
        self.assertNotIn('/bill', (self.static / 'routes.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
