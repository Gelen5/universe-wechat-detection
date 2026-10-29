"""Failover and monitoring: a dead relay must not be silent.

The relay behind every writing node answered 502 for hours. These tests pin the
three defences added for it: a configured fallback relay, a beat-scheduled probe,
and an admin check that reports the probe result.
"""
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from tests import support  # noqa: F401 - isolated account database
from server import celery_app as celery_module, provider_health, qihaoshou, workbench
from server.main import app
from server.providers.base import ProviderRequestError


def _settings(mapping):
    def read(name, default=''):
        return mapping.get(name, default)
    return read


class FailoverProfileTests(unittest.TestCase):
    def test_without_a_fallback_only_the_primary_is_used(self):
        with patch.object(workbench, '_setting', side_effect=_settings({
                'WECHAT_TEXT_API_BASE_URL': 'https://primary.example/v1',
                'WECHAT_TEXT_API_KEY': 'k1', 'WECHAT_TEXT_MODEL': 'm1'})):
            profiles = workbench._text_profiles(None, None)
        self.assertEqual(['primary'], [p['name'] for p in profiles])

    def test_a_configured_fallback_is_appended(self):
        with patch.object(workbench, '_setting', side_effect=_settings({
                'WECHAT_TEXT_API_BASE_URL': 'https://primary.example/v1',
                'WECHAT_TEXT_API_KEY': 'k1', 'WECHAT_TEXT_MODEL': 'm1',
                'WECHAT_TEXT_FALLBACK_API_BASE_URL': 'https://backup.example',
                'WECHAT_TEXT_FALLBACK_API_KEY': 'k2'})):
            profiles = workbench._text_profiles(None, None)
        self.assertEqual(['primary', 'fallback'], [p['name'] for p in profiles])
        self.assertEqual('https://backup.example', profiles[1]['base_url'])
        self.assertEqual('m1', profiles[1]['model'])

    def test_an_explicit_base_url_never_reaches_the_fallback(self):
        with patch.object(workbench, '_setting', side_effect=_settings({
                'WECHAT_TEXT_API_KEY': 'k1',
                'WECHAT_TEXT_FALLBACK_API_BASE_URL': 'https://backup.example',
                'WECHAT_TEXT_FALLBACK_API_KEY': 'k2'})):
            profiles = workbench._text_profiles(None, 'https://explicit.example/v1')
        self.assertEqual(['primary'], [p['name'] for p in profiles])


class TextFailoverTests(unittest.TestCase):
    def _providers(self, outcomes):
        """Fake providers/services that record which relay served the call."""

        class FakeProvider:
            def __init__(self, **kwargs):
                self.base_url = kwargs['base_url']

        class FakeService:
            def __init__(self, provider, **kwargs):
                self.provider = provider

            def create_response(self, *args, **kwargs):
                outcome = outcomes(self.provider.base_url)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        return FakeProvider, FakeService

    def test_outage_moves_to_the_fallback_relay(self):
        ok = Mock()
        ok.text = 'from backup'
        outage = ProviderRequestError('boom', code='provider_unavailable', transient=True, status_code=502)
        settings = {
            'WECHAT_TEXT_API_BASE_URL': 'https://primary.example/v1',
            'WECHAT_TEXT_API_KEY': 'k1', 'WECHAT_TEXT_MODEL': 'm1',
            'WECHAT_TEXT_FALLBACK_API_BASE_URL': 'https://backup.example',
            'WECHAT_TEXT_FALLBACK_API_KEY': 'k2',
            'WECHAT_TEXT_ATTEMPTS': '1',
        }
        seen = []

        def outcome(base):
            seen.append(base)
            return outage if base.startswith('https://primary') else ok

        FakeProvider, FakeService = self._providers(outcome)
        with patch.object(workbench, '_setting', side_effect=_settings(settings)), \
             patch.object(workbench, '_verify_ssl', return_value=True), \
             patch('server.providers.ModelService', FakeService), \
             patch('server.providers.OpenAICompatibleProvider', FakeProvider):
            text = workbench._text('prompt')
        self.assertEqual('from backup', text)
        self.assertEqual(['https://primary.example/v1', 'https://backup.example'], seen)

    def test_both_relays_down_raises_the_user_facing_message(self):
        from server.providers.base import USER_UNAVAILABLE_MESSAGE
        settings = {
            'WECHAT_TEXT_API_BASE_URL': 'https://primary.example/v1',
            'WECHAT_TEXT_API_KEY': 'k1', 'WECHAT_TEXT_MODEL': 'm1',
            'WECHAT_TEXT_FALLBACK_API_BASE_URL': 'https://backup.example',
            'WECHAT_TEXT_FALLBACK_API_KEY': 'k2',
            'WECHAT_TEXT_ATTEMPTS': '1',
        }
        seen = []

        def outcome(base):
            seen.append(base)
            return ProviderRequestError('down', code='provider_unavailable',
                                        transient=True, status_code=502)

        FakeProvider, FakeService = self._providers(outcome)
        with patch.object(workbench, '_setting', side_effect=_settings(settings)), \
             patch.object(workbench, '_verify_ssl', return_value=True), \
             patch('server.providers.ModelService', FakeService), \
             patch('server.providers.OpenAICompatibleProvider', FakeProvider):
            with self.assertRaises(workbench.ProviderError) as caught:
                workbench._text('prompt')
        self.assertEqual(USER_UNAVAILABLE_MESSAGE, str(caught.exception))
        self.assertTrue(any('backup' in base for base in seen))


class StreamFailoverTests(unittest.TestCase):
    """A finished primary stream must not be replayed on the fallback relay."""

    def _stream(self, responses):
        """Serve one scripted SSE body per provider and record which ran."""
        calls = []

        class FakeResponse:
            def __init__(self, status, payload, headers):
                self.status_code = status
                self.text = payload
                self.headers = headers
                self.ok = status == 200
                self.encoding = None

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def iter_lines(self, **kwargs):
                return iter(responses.pop(0))

        class FakeSession:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def post(self, url, **kwargs):
                calls.append(url)
                return FakeResponse(200, '', {'Content-Type': 'text/event-stream'})

        settings = {
            'WECHAT_TEXT_API_BASE_URL': 'https://primary.example',
            'WECHAT_TEXT_API_KEY': 'k1', 'WECHAT_TEXT_MODEL': 'gpt-6.1-sol',
            'WECHAT_TEXT_FALLBACK_API_BASE_URL': 'https://backup.example',
            'WECHAT_TEXT_FALLBACK_API_KEY': 'k2',
        }
        import threading
        with patch.object(workbench, '_setting', side_effect=_settings(settings)), \
             patch.object(workbench, '_headers', return_value={'Authorization': 'Bearer x'}), \
             patch.object(workbench, '_verify_ssl', return_value=True), \
             patch.object(qihaoshou.requests, 'Session', FakeSession):
            tokens = list(qihaoshou.text_stream('prompt', threading.Event()))
        return tokens, calls

    def test_primary_success_returns_without_touching_the_fallback(self):
        from server import qihaoshou
        body = [
            'data: {"type":"response.output_text.delta","delta":"hello "}',
            'data: {"type":"response.output_text.delta","delta":"world"}',
            'data: {"type":"response.completed","response":{"status":"completed","output":[]}}',
        ]
        tokens, calls = self._stream([body])
        self.assertEqual(['hello ', 'world'], tokens)
        self.assertEqual(1, len(calls))
        self.assertIn('primary', calls[0])


class HealthMonitorTests(unittest.TestCase):
    def test_probe_reports_failure_detail(self):
        done = Mock(returncode=1, stdout='FAIL gpt-6.1-sol 502', stderr='')
        with patch.object(provider_health.subprocess, 'run', return_value=done):
            result = provider_health.probe_text_provider()
        self.assertFalse(result['ok'])
        self.assertIn('502', result['detail'])

    def test_probe_reports_success(self):
        done = Mock(returncode=0, stdout='ok gpt-6.1-sol', stderr='')
        with patch.object(provider_health.subprocess, 'run', return_value=done):
            self.assertTrue(provider_health.probe_text_provider()['ok'])

    def test_probe_timeout_is_a_failure_not_a_crash(self):
        import subprocess
        with patch.object(provider_health.subprocess, 'run',
                          side_effect=subprocess.TimeoutExpired('probe', 1)):
            result = provider_health.probe_text_provider(timeout=1)
        self.assertFalse(result['ok'])
        self.assertIn('timed out', result['detail'])

    def test_beat_schedules_the_probe_on_a_consumed_queue(self):
        schedule = celery_module.celery_app.conf.beat_schedule
        self.assertIn('provider-health', schedule)
        self.assertEqual('provider.health', schedule['provider-health']['task'])
        route = celery_module.celery_app.conf.task_routes['provider.health']['queue']
        self.assertEqual('text', route)

    def test_admin_endpoint_requires_admin(self):
        client = TestClient(app)
        client.post('/api/auth/register', json={
            'email': f'health-{id(self)}@example.com',
            'password': 'testing-pass-123', 'display_name': 'h'})
        response = client.get('/api/admin/provider-health')
        self.assertEqual(403, response.status_code)


if __name__ == '__main__':
    unittest.main()

