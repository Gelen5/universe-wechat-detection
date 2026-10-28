"""Length targets are enforced for a single requested number, not just ranges.

A user who asks for "1200字" got 1986 characters from one-click writing and 917
from the agent draft, and both were reported as success. These tests pin the
band, the open-ended forms, and the single-retry contract.
"""
import unittest
from unittest.mock import patch

from tests import support  # noqa: F401 - isolated account database
from server import qihaoshou, skill_runtime


def body(chars):
    # ASCII heading so the Chinese character count equals `chars` exactly.
    return '# Title\n' + '字' * chars


class LengthBoundsTests(unittest.TestCase):
    def test_explicit_range_is_exact(self):
        self.assertEqual((800, 1000, '要求 800—1000 字'),
                         skill_runtime.length_bounds('800—1000字'))

    def test_single_target_becomes_a_tolerance_band(self):
        with patch.dict('os.environ', {'WECHAT_LENGTH_TOLERANCE': '0.2'}):
            low, high, description = skill_runtime.length_bounds('1200字左右')
        self.assertEqual((960, 1440), (low, high))
        self.assertIn('1200', description)

    def test_tolerance_is_configurable_and_invalid_values_fall_back(self):
        with patch.dict('os.environ', {'WECHAT_LENGTH_TOLERANCE': '0.1'}):
            self.assertEqual((1080, 1320), skill_runtime.length_bounds('1200字')[:2])
        for bad in ('abc', '0.9', '-1'):
            with patch.dict('os.environ', {'WECHAT_LENGTH_TOLERANCE': bad}):
                self.assertEqual((960, 1440), skill_runtime.length_bounds('1200字')[:2], bad)

    def test_open_ended_forms(self):
        self.assertEqual((1, 800), skill_runtime.length_bounds('不超过800字')[:2])
        self.assertEqual((1, 800), skill_runtime.length_bounds('800字以内')[:2])
        self.assertEqual((1500, None), skill_runtime.length_bounds('至少1500字')[:2])
        self.assertEqual((1500, None), skill_runtime.length_bounds('1500字以上')[:2])

    def test_no_length_means_no_check(self):
        self.assertIsNone(skill_runtime.length_bounds('随便写一篇'))
        self.assertIsNone(skill_runtime.length_issue(body(50), '随便写一篇'))

    def test_issue_reports_count_and_band(self):
        issue = skill_runtime.length_issue(body(800), '1200字左右')
        self.assertIn('800', issue)
        self.assertIn('960', issue)
        self.assertIsNone(skill_runtime.length_issue(body(1200), '1200字左右'))


class OneClickLengthEnforcementTests(unittest.TestCase):
    def test_in_band_body_is_not_rewritten(self):
        calls = []
        text, unmet = qihaoshou.enforce_length(body(1200), '1200字', lambda issue: calls.append(issue) or body(1200))
        self.assertEqual(body(1200), text)
        self.assertIsNone(unmet)
        self.assertEqual([], calls)

    def test_out_of_band_body_is_rewritten_once(self):
        calls = []
        text, unmet = qihaoshou.enforce_length(
            body(1900), '1200字', lambda issue: calls.append(issue) or body(1250))
        self.assertEqual(body(1250), text)
        self.assertIsNone(unmet)
        self.assertEqual(1, len(calls))
        self.assertIn('1900', calls[0])

    def test_unusable_rewrite_keeps_the_original(self):
        text, unmet = qihaoshou.enforce_length(body(1900), '1200字', lambda issue: '短')
        self.assertEqual(body(1900), text)
        self.assertIn('1900', unmet)

    def test_progress_is_reported_only_while_rewriting(self):
        seen = []
        qihaoshou.enforce_length(body(1200), '1200字', lambda issue: body(1200), on_progress=seen.append)
        self.assertEqual([], seen)
        qihaoshou.enforce_length(body(1900), '1200字', lambda issue: body(1250), on_progress=seen.append)
        self.assertEqual(1, len(seen))


if __name__ == '__main__':
    unittest.main()
