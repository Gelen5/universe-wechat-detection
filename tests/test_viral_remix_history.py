"""Durable history, isolation, and partial-image preservation for remix jobs."""
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import tests.support  # noqa: F401 - isolated SQLite database

from fastapi import HTTPException
from server import accounts, main, viral_remix_jobs


@pytest.fixture
def users():
    accounts.init_db()
    suffix = uuid.uuid4().hex
    first = accounts.create_user(f'first-{suffix}@example.com', 'password12345', 'first')
    second = accounts.create_user(f'second-{suffix}@example.com', 'password12345', 'second')
    return first, second


def request(user):
    return SimpleNamespace(state=SimpleNamespace(user=user))


def create_job(user, url, suffix):
    job = accounts.create_job(user['id'], viral_remix_jobs.TASK_TYPE, 'image', suffix, None,
                              {'session_id': 'same-session', 'count': 1})
    accounts.claim_job(['image'], job['id'])
    accounts.progress_job(job['id'], done=1, total=1, stage='generating', images=[{'url': url, 'index': 1}])
    accounts.finish_job(job['id'], {'images': [{'url': url, 'index': 1}]})
    return job


def test_history_is_account_scoped_and_pageable(users):
    first, second = users
    a = create_job(first, '/api/creator-tools/assets/tie-tu/legacy/remix-01.jpg', 'a')
    b = create_job(first, '/api/creator-tools/assets/tie-tu/remix-new/remix-01.jpg', 'b')
    create_job(second, '/api/creator-tools/assets/tie-tu/other/remix-01.jpg', 'c')
    result = main.viral_remix_history(request(first), limit=1)
    assert len(result['jobs']) == 1 and result['next_before']
    next_page = main.viral_remix_history(request(first), limit=1, before=result['next_before'])
    assert {result['jobs'][0]['id'], next_page['jobs'][0]['id']} == {a['id'], b['id']}
    assert all('other' not in str(x) for x in result['jobs'] + next_page['jobs'])
    with pytest.raises(HTTPException):
        main.viral_remix_history(request(second), before=a['id'])


def test_partial_images_survive_failed_job(users):
    first, _ = users
    job = accounts.create_job(first['id'], viral_remix_jobs.TASK_TYPE, 'image', 'partial', None,
                              {'session_id': 'partial-session', 'count': 2})
    accounts.claim_job(['image'], job['id'])
    images = [{'url': '/api/creator-tools/assets/tie-tu/partial/remix-01.jpg', 'index': 1}]
    accounts.progress_job(job['id'], done=1, total=2, stage='generating', images=images)
    accounts.fail_job(job['id'], 'interrupted')
    result = main.viral_remix_history(request(first))
    recovered = next(item for item in result['jobs'] if item['id'] == job['id'])
    assert recovered['status'] == 'failed' and recovered['images'] == images


def test_jobs_in_same_session_do_not_overwrite_each_other(users, monkeypatch, tmp_path):
    from server import creator_tools, viral_remix_tasks, workbench
    first, _ = users
    monkeypatch.setattr(workbench, 'provider_overrides', lambda: nullcontext())
    monkeypatch.setattr(creator_tools, 'prepare_remix_cards', lambda session_id, idea: ([{}], idea, tmp_path / 'same-session'))
    def fake_card(idea, page, index, total, directory):
        image = directory / 'remix-01.jpg'
        image.write_bytes(idea['content'].encode())
        return {'index': index, 'url': f'/api/creator-tools/assets/tie-tu/{directory.name}/{image.name}'}
    monkeypatch.setattr(creator_tools, 'generate_remix_card', fake_card)
    paths = []
    for value in ('first', 'second'):
        job = accounts.create_job(first['id'], viral_remix_jobs.TASK_TYPE, 'image', value, None,
                                  {'session_id': 'same-session', 'idea': {'content': value}, 'count': 1})
        assert viral_remix_tasks.run.run(job['id'])['status'] == 'succeeded'
        paths.append(tmp_path / f'remix-{job["id"]}' / 'remix-01.jpg')
    assert paths[0] != paths[1]
    assert [path.read_bytes() for path in paths] == [b'first', b'second']
