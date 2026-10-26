"""HTML entries must not retain stale asset manifests between releases."""
from tests import support
from fastapi.testclient import TestClient
from server.main import app
import pytest


@pytest.mark.parametrize('path', ['/', '/workbench', '/workbench?conversation=example', '/xiaohongshu', '/morning-generator', '/bookshelf', '/market', '/qihaoshou'])
def test_frontend_entries_and_assets_do_not_store_stale_versions(path):
    with TestClient(app) as client:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store, max-age=0'
        assert response.headers['pragma'] == 'no-cache'


def test_public_static_cache_contract_and_no_session_lookup(monkeypatch):
    from server import accounts
    with TestClient(app) as client:
        def forbidden_lookup(request):
            raise AssertionError('Public static requests must not query account sessions')
        monkeypatch.setattr(accounts, 'user_from_request', forbidden_lookup)
        plain = client.get('/static/wechat-mint.css')
        assert plain.status_code == 200
        assert plain.headers['cache-control'] == 'public, max-age=0, must-revalidate'
        versioned = client.get('/static/wechat-mint.css?v=test-release')
        assert versioned.status_code == 200
        assert versioned.headers['cache-control'] == 'public, max-age=31536000, immutable'
