"""HTML entries must not retain stale asset manifests between releases."""
from tests import support
from fastapi.testclient import TestClient
from server.main import app
from pathlib import Path
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


def test_unauthenticated_api_response_cannot_be_cached_for_the_next_login():
    with TestClient(app) as client:
        response = client.get('/api/runs')
        assert response.status_code == 401
        assert response.headers['cache-control'] == 'private, no-store, max-age=0'


def test_private_response_identifies_request_owner_for_stale_ui_guard():
    with TestClient(app) as client:
        login = client.post('/api/auth/login', json={
            'email': 'admin@example.com', 'password': 'testing-pass-123'})
        assert login.status_code == 200
        response = client.get('/api/runs')
        assert response.status_code == 200
        assert response.headers['X-Account-ID'] == login.json()['user']['id']
        # Identity bootstrap cannot wait on the identity it is establishing.
        assert 'X-Account-ID' not in client.get('/api/auth/me').headers


def test_render_controlling_bundles_never_pin_a_year_long_immutable_cache():
    """A stale app.js hid every panel on /xhs-extract and painted a blank page.

    These files decide what renders, so even a versioned URL must revalidate.
    Anything else may keep the long cache.
    """
    controlling = ('/static/app.js', '/static/routes.js', '/static/shell.js',
                   '/static/app-navigation.js', '/static/notion-workspace.js',
                   '/static/sidebar.js')
    with TestClient(app) as client:
        for path in controlling:
            response = client.get(path + '?v=test-release')
            assert response.status_code == 200, path
            assert 'immutable' not in response.headers['cache-control'], path
    with TestClient(app) as client:
        # Non-controlling assets still get the long cache, so the extra
        # revalidation is a deliberate exception rather than a global regression.
        plain = client.get('/static/wechat-mint.css?v=test-release')
        assert 'immutable' in plain.headers['cache-control']


def test_new_view_is_declared_in_both_the_page_and_the_bundle():
    """The section and its view registration must ship together.

    A section without a view mapping is invisible; a view mapping without a
    section makes every panel hide.
    """
    root = Path(__file__).resolve().parents[1]
    html = (root / 'static/index.html').read_text(encoding='utf-8')
    bundle = (root / 'static/app.js').read_text(encoding='utf-8')
    for view in ('xhs-extract', 'douyin-extract', 'viral-remix'):
        assert f'id="{view}"' in html, f'{view} section missing from index.html'
        assert f"'{view}':" in bundle, f'{view} missing from app.js view map'

