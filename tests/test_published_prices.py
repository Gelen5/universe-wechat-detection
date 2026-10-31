"""Published prices: a picture costs 2 毛, a card plan costs 2 毛.

Points are sold at ¥0.10 each (10 元 / 100 积分), so the defaults below are the
published rate expressed in points. The image price must be identical on every
surface: the same model billed 2 points on one page and 30 on another is the
kind of inconsistency a paying user finds first.
"""
import unittest

from tests import support  # noqa: F401 - isolated account database
from server.accounts import DEFAULT_PRICING


def _defaults():
    return {(method, path): points for method, path, _feature, points, _cost in DEFAULT_PRICING}


class PublishedPriceTests(unittest.TestCase):
    def test_every_image_surface_costs_two_points(self):
        defaults = _defaults()
        for path in ('/api/creator-tools/image', '/api/images/generations', '/api/qihaoshou/image'):
            with self.subTest(path=path):
                self.assertEqual(2, defaults[('POST', path)])

    def test_card_plan_costs_two_points(self):
        # 2026-10-31 由 1 调成 2：策划一次要跑一轮完整模型调用，和配图同价。
        self.assertEqual(2, _defaults()[('POST', '/api/tie-tu/plan')])

    def test_viral_remix_steps_are_priced_apart_from_the_card_plan(self):
        defaults = _defaults()
        self.assertEqual(2, defaults[('POST', '/api/viral-remix/analyze')])
        self.assertEqual(2, defaults[('POST', '/api/viral-remix/image')])

    def test_article_writing_price_is_unchanged(self):
        defaults = _defaults()
        self.assertEqual(10, defaults[('POST', '/api/qihaoshou/generate')])
        self.assertEqual(30, defaults[('POST', '/api/workbench/sessions')])

    def test_point_value_matches_the_sale_ratio(self):
        # 10 元 = 100 积分 -> ¥0.10 per point; /api/pricing publishes this too.
        import inspect
        from server import main
        source = inspect.getsource(main)
        self.assertIn('"face_value_cny": 0.1', source)

    def test_reseeding_does_not_rewrite_an_existing_price(self):
        """改 DEFAULT_PRICING 对已有库无效——这是故意的，也是改价最容易踩的坑。

        价格行只在首次建库时写入（INSERT OR IGNORE），所以线上调价必须另跑
        UPDATE。反过来，人工 SQL 调过的价格也不会被重启悄悄覆盖，漂移由启动
        日志里的 pricing_rules drift 报警兜住。
        """
        from server import accounts

        try:
            self._set_points("/api/tie-tu/plan", 7)
            accounts.init_db()  # 重新播种
            self.assertEqual(7, self._points("/api/tie-tu/plan"))
        finally:
            self._set_points("/api/tie-tu/plan", 2)

    @staticmethod
    def _set_points(path, points):
        from server import accounts
        with accounts.DB_LOCK, accounts._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("UPDATE pricing_rules SET points=? WHERE path=?", (points, path))
            connection.execute("COMMIT")

    @staticmethod
    def _points(path):
        from server import accounts
        with accounts.DB_LOCK, accounts._connect() as connection:
            return connection.execute(
                "SELECT points FROM pricing_rules WHERE path=?", (path,)
            ).fetchone()["points"]


if __name__ == '__main__':
    unittest.main()
