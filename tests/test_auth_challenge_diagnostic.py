from unittest.mock import patch
from fastapi.testclient import TestClient
from tests import support  # noqa: F401
from server.main import app
from server.rate_limit import LimitResult


def test_public_diagnostic_accepts_only_bounded_codes_and_never_logs_credentials(caplog):
    client = TestClient(app)
    with patch('server.main.check_behavior_observation', return_value=LimitResult(True)):
        response = client.post('/api/auth/challenge-diagnostic', json={
            'code': '600010', 'action': 'register_email', 'email': 'private@example.test',
            'password': 'private-password', 'token': 'private-token'})
        assert response.status_code == 204
        assert 'turnstile_client_error code=600010 action=register_email' in caplog.text
        assert 'private' not in caplog.text
        assert client.post('/api/auth/challenge-diagnostic', json={
            'code': 'private-email', 'action': 'register_email'}).status_code == 422


def test_rate_limited_diagnostic_does_not_write_logs(caplog):
    client = TestClient(app)
    with patch('server.main.check_behavior_observation', return_value=LimitResult(False)):
        assert client.post('/api/auth/challenge-diagnostic', json={'code':'600010','action':'register'}).status_code == 204
    assert 'turnstile_client_error' not in caplog.text
