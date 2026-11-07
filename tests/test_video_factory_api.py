from pathlib import Path
import uuid

import pytest
from fastapi.testclient import TestClient
from tests import support  # noqa: F401

from server import accounts
from server.main import app


def _factory_user():
    client = TestClient(app)
    admin = TestClient(app)
    email = f"video-factory-{uuid.uuid4().hex[:12]}@example.com"
    user = client.post('/api/auth/register', json={
        'email': email, 'password': 'testing-pass-123',
    }).json()['user']
    assert admin.post('/api/auth/login', json={
        'email': 'admin@example.com', 'password': 'testing-pass-123',
    }).status_code == 200
    assert admin.post('/api/admin/recharge', json={
        'user_id': user['id'], 'points': 20, 'bucket': 'trial', 'note': 'video-test',
    }).status_code == 200
    return client, user


def test_disabled_factory_keeps_public_page_closed(monkeypatch):
    monkeypatch.setenv('VIDEO_FACTORY_ENABLED', 'false')
    client, _ = _factory_user()
    assert TestClient(app).get('/video-factory').status_code == 200
    assert TestClient(app).get('/video-factory-frame').status_code == 200
    config = client.get('/api/video-factory/config').json()
    assert config['enabled'] is False
    response = client.post('/api/video-factory/jobs', json={
        'category': 'book', 'topic': '曾国藩家书', 'duration': 45,
        'idempotency_key': 'video-disabled-test',
    })
    assert response.status_code == 503


def test_create_video_job_reuses_points_and_does_not_duplicate(monkeypatch, tmp_path):
    monkeypatch.setenv('VIDEO_FACTORY_ENABLED', 'true')
    monkeypatch.setenv('VIDEO_FACTORY_POINTS', '7')
    client, user = _factory_user()
    monkeypatch.setattr(
        'server.video_factory_tasks.run_video_factory.apply_async',
        lambda *args, **kwargs: None,
    )
    payload = {
        'category': 'book', 'topic': '曾国藩家书', 'duration': 45,
        'visual_style': 'chinese', 'voice_id': 'zh-CN-XiaoxiaoNeural-Female',
        'sources': [{'url': 'https://example.com/source',
                     'summary': '资料来源摘要足够长，仍需人工核实其事实依据。'}],
        'idempotency_key': 'video-create-idempotent',
    }
    first = client.post('/api/video-factory/jobs', json=payload)
    assert first.status_code == 202, first.text
    job_id = first.json()['job']['id']
    assert first.json()['estimated_points'] == 7
    assert accounts.wallet_summary(user['id'])['balance'] == 13
    second = client.post('/api/video-factory/jobs', json=payload)
    assert second.status_code == 202, second.text
    assert second.json()['job']['id'] == job_id
    assert accounts.wallet_summary(user['id'])['balance'] == 13

    # Only the owner can see the job. The public response never exposes storage keys.
    other = TestClient(app)
    assert other.get(f'/api/video-factory/jobs/{job_id}').status_code == 401
    assert client.get(f'/api/video-factory/jobs/{job_id}').json()['job']['id'] == job_id


def test_completed_factory_asset_is_owner_only(monkeypatch, tmp_path):
    monkeypatch.setenv('VIDEO_FACTORY_ENABLED', 'true')
    monkeypatch.setenv('VIDEO_FACTORY_POINTS', '0')
    client, user = _factory_user()
    job = accounts.create_job(
        user['id'], 'video_factory', 'image', 'existing-asset-job', None, {},
    )
    accounts.claim_job(['image'], job_id=job['id'])
    accounts.finish_job(job['id'], {'assets': {'video': {
        'key': 'video-factory/key.mp4', 'url': '/api/storage/video-factory/key.mp4',
        'size': 5, 'content_type': 'video/mp4',
    }}})
    # The wrong owner gets the same 404 as a missing job, not a redirect to storage.
    assert TestClient(app).get(
        f"/api/video-factory/jobs/{job['id']}/assets/video",
    ).status_code == 401


def test_factory_page_registers_navigation_and_iframe():
    root = Path(__file__).resolve().parents[1]
    index = (root / 'static/index.html').read_text(encoding='utf-8')
    app_js = (root / 'static/app.js').read_text(encoding='utf-8')
    routes = (root / 'static/routes.js').read_text(encoding='utf-8')
    assert 'id="video-factory"' in index
    assert "data-view=\"video-factory\"" in index
    assert "'video-factory': document.querySelector('#video-factory')" in app_js
    assert "href: '/video-factory'" in routes


def test_job_slots_limit_video_workers_and_release_by_token():
    user = accounts.create_user(
        f'slots-{uuid.uuid4().hex[:12]}@example.com', 'testing-pass-123', 'slots'
    )
    first = accounts.create_job(user['id'], 'video_factory', 'image', 'slot-first', None, {})
    second = accounts.create_job(user['id'], 'video_factory', 'image', 'slot-second', None, {})
    accounts.claim_job(['image'], job_id=first['id'])
    accounts.claim_job(['image'], job_id=second['id'])
    token, state = accounts.acquire_job_slot('video_test', first['id'], 1, 60)
    assert token
    assert state == 'acquired'
    assert accounts.acquire_job_slot('video_test', first['id'], 1, 60) == (None, 'same_job')
    assert accounts.acquire_job_slot('video_test', second['id'], 1, 60) == (None, 'full')
    assert accounts.renew_job_slot('video_test', first['id'], token, 60) is True
    accounts.release_job_slot(first['id'], token)
    second_token, state = accounts.acquire_job_slot('video_test', second['id'], 1, 60)
    assert second_token
    assert state == 'acquired'
    accounts.release_job_slot(second['id'], second_token)


def test_provider_url_download_rejects_non_public_https(monkeypatch):
    from server.video_factory_service import generate_scene_image
    from server.video_factory_mpt import ScenePlan
    from server import workbench
    from server import image_provider
    scene = ScenePlan(sequence=1, narration='测试', duration_target=30, visual_prompt='书页')
    monkeypatch.setattr(image_provider, 'generate', lambda *_args, **_kwargs: {
        'data': [{'url': 'http://127.0.0.1/private.png'}]
    })
    class Overrides:
        def __enter__(self): return None
        def __exit__(self, *_args): return False
    monkeypatch.setattr(workbench, 'provider_overrides', lambda **_kwargs: Overrides())
    with pytest.raises(ValueError, match='public HTTPS'):
        generate_scene_image(scene, Path('/tmp/not-written.png'), 'unsafe-url-test')
