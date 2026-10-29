"""Published prices: a picture costs 2 毛, a strategy 1 毛.

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

    def test_strategy_generation_costs_one_point(self):
        self.assertEqual(1, _defaults()[('POST', '/api/tie-tu/plan')])

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


if __name__ == '__main__':
    unittest.main()
