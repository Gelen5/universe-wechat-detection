"""HTML entries must not retain stale asset manifests between releases."""
from tests import support
from fastapi.testclient import TestClient
from server.main import app
import pytest


@pytest.mark.parametrize('path', ['/', '/workbench', '/workbench?conversation=example', '/xiaohongshu', '/morning-generator', '/bookshelf', '/market', '/qihaoshou', '/static/wechat-mint.css'])
def test_frontend_entries_and_assets_do_not_store_stale_versions(path):
    with TestClient(app) as client:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store, max-age=0'
        assert response.headers['pragma'] == 'no-cache'
