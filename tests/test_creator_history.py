import json
import uuid
from types import SimpleNamespace

import pytest
import tests.support  # noqa: F401
from fastapi import HTTPException
from server import accounts, main, article_visual


@pytest.fixture
def users():
    accounts.init_db()
    suffix = uuid.uuid4().hex
    return [accounts.create_user(f'history-{i}-{suffix}@example.com', 'password12345', 'creator') for i in range(2)]


def request(user):
    return SimpleNamespace(state=SimpleNamespace(user=user))


def test_remix_migration_history_and_isolation(users):
    user, other = users
    result = {'content_guess': '旧创作', 'ideas': []}
    generated = [{'url': '/api/creator-tools/assets/tie-tu/old/remix-01.jpg'}]
    main.import_remix_history('oldsession123', main.RemixHistoryImport(result=result, generated=generated), request(user))
    main.import_remix_history('oldsession123', main.RemixHistoryImport(result={'content_guess': '不应覆盖'}), request(user))
    assert main.creator_history_item('analysis', 'oldsession123', request(user))['item']['result'] == result
    assert main.creator_history_item('analysis', 'oldsession123', request(user))['item']['generated'] == generated
    assert main.creator_history(request(user), 'viral-remix')['items'][0]['title'] == '旧创作'
    assert main.creator_history(request(other), 'viral-remix')['items'] == []
    with pytest.raises(HTTPException):
        main.creator_history_item('analysis', 'oldsession123', request(other))


def test_tie_plan_history_and_associated_images(users):
    user, other = users
    job = accounts.create_job(user['id'], 'tie_tu', 'light', uuid.uuid4().hex, None, {})
    accounts.claim_job(['light'], job['id'])
    accounts.finish_job(job['id'], {'plan': {'title': '贴图计划', 'session_id': 'plan-session', 'cards': []}})
    image_job = accounts.create_job(user['id'], 'creator_image', 'image', uuid.uuid4().hex, None, {'tool': 'tie-tu', 'session_id': 'plan-session'})
    accounts.claim_job(['image'], image_job['id'])
    accounts.finish_job(image_job['id'], {'image': {'index': 1, 'url': '/image.png'}})
    assert main.creator_history(request(user), 'tie-tu')['items'][0]['title'] == '贴图计划'
    assert main.creator_history_item('plan', job['id'], request(user))['item']['images'][0]['url'] == '/image.png'
    with pytest.raises(HTTPException):
        main.creator_history_item('plan', job['id'], request(other))


def test_article_history_is_scoped_and_pageable(users, monkeypatch, tmp_path):
    user, other = users
    monkeypatch.setattr(article_visual, 'JOBS_DIR', tmp_path)
    for i in range(3):
        article_visual._write_job({'id': f'job{i}-{uuid.uuid4().hex[:8]}', 'user_id': user['id'], 'article': {'title': f'文章{i}'}, 'plan': {'slots': []}, 'images': {}})
    page = article_visual.list_article_visual_history(request(user), limit=2)
    assert len(page['items']) == 2 and page['next_before']
    assert len(article_visual.list_article_visual_history(request(user), limit=2, before=page['next_before'])['items']) == 1
    assert article_visual.list_article_visual_history(request(other))['items'] == []
    with pytest.raises(HTTPException):
        article_visual.list_article_visual_history(request(other), before=page['next_before'])
