"""Upstream outages must not hand the end user an operator checklist.

The 502 that took the writing paths down surfaced
"模型服务返回 HTTP 502，请管理员检查凭据、模型权限与IP白名单" to paying users.
The status and body now go to the log; the user gets one actionable sentence.
"""
import contextlib
import unittest
from unittest.mock import patch

from tests import support  # noqa: F401 - isolated account database
from server import workbench
from server.providers.base import USER_UNAVAILABLE_MESSAGE


class _FakeResponse:
    def __init__(self, status, text='', headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}
        self.ok = 200 <= status < 300

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self, **kwargs):
        return iter(())

    def json(self):
        try:
            import json
            return json.loads(self.text)
        except ValueError:
            raise


class _FakeSession:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, *args, **kwargs):
        return self._response


def _settings(name, default=''):
    return {'WECHAT_TEXT_API_BASE_URL': 'https://relay.example/v1',
            'WECHAT_TEXT_API_KEY': 'test-key',
            'WECHAT_TEXT_MODEL': 'test-model'}.get(name, default)


class ProviderErrorMessageTests(unittest.TestCase):



    def _post_error(self, response):
        with patch.object(workbench.requests, 'Session', lambda: _FakeSession(response)), \
             patch.object(workbench, '_api_url', return_value='https://relay.example/v1/responses'), \
             patch.object(workbench, '_headers', return_value={}), \
             patch.object(workbench, '_verify_ssl', return_value=True):
            workbench._post('text', 'responses', {}, 30)

    def test_post_5xx_and_429_are_user_facing(self):
        for status in (500, 502, 503, 429):
            with self.subTest(status=status), self.assertRaises(workbench.ProviderError) as caught:
                self._post_error(_FakeResponse(status, '{"error":{"message":"upstream down"}}',
                                               {'Content-Type': 'application/json'}))
            self.assertEqual(USER_UNAVAILABLE_MESSAGE, str(caught.exception))

    def test_post_4xx_keeps_the_actionable_detail(self):
        with self.assertRaises(workbench.ProviderError) as caught:
            self._post_error(_FakeResponse(400, '{"error":{"message":"model not found"}}',
                                           {'Content-Type': 'application/json'}))
        self.assertIn('model not found', str(caught.exception))

    def test_no_module_still_prints_the_operator_checklist_to_users(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / 'server'
        offenders = [str(path.relative_to(root)) for path in root.rglob('*.py')
                     if '请管理员检查凭据' in path.read_text(encoding='utf-8')]
        self.assertEqual([], offenders)


if __name__ == '__main__':
    unittest.main()
