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
    monkeypatch.setattr(creator_tools, 'remix_publication_copy', lambda images: {'titles': ['标题一', '标题二', '标题三'], 'body': '配文', 'tags': ['标签']})
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


def test_publication_is_scoped_and_persisted(users):
    first, second = users
    job = create_job(first, '/api/creator-tools/assets/tie-tu/a/remix-01.jpg', 'copy')
    payload = main.RemixPublicationRequest(titles=['标题一', '标题二', '标题三'], body='发布正文', tags=['生活'])
    with pytest.raises(HTTPException) as denied:
        main.save_remix_publication(job['id'], payload, request(second))
    assert denied.value.status_code == 404
    main.save_remix_publication(job['id'], payload, request(first))
    found = next(item for item in main.viral_remix_history(request(first))['jobs'] if item['id'] == job['id'])
    assert found['publication']['body'] == '发布正文'
    payload.titles[0] = '字' * 21
    with pytest.raises(HTTPException) as invalid:
        main.save_remix_publication(job['id'], payload, request(first))
    assert invalid.value.status_code == 422


def test_copy_uses_only_successful_images(monkeypatch, tmp_path):
    from server import creator_tools, workbench
    from PIL import Image
    image = tmp_path / 'image.jpg'
    Image.new('RGB', (4, 4), 'red').save(image)
    seen = []
    monkeypatch.setattr(creator_tools, 'creator_asset', lambda *args: image)
    monkeypatch.setattr(workbench, '_api_url', lambda *args: 'https://example.test')
    monkeypatch.setattr(workbench, '_headers', lambda *args: {})
    monkeypatch.setattr(workbench, '_setting', lambda *args: 'vision-model')
    monkeypatch.setattr(workbench, '_verify_ssl', lambda: True)
    class Response:
        def raise_for_status(self): pass
        def json(self): return {'choices': [{'message': {'content': '{"titles":["一","二","三"],"body":"正文","tags":["标签"]}'}}]}
    monkeypatch.setattr(creator_tools.requests, 'post', lambda *a, **kw: (seen.append(kw['json']) or Response()))
    creator_tools.remix_publication_copy([{'index': 1, 'url': '/api/creator-tools/assets/tie-tu/a/remix-01.jpg'}])
    assert len(seen[0]['messages'][0]['content']) == 2
    assert seen[0]['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')


def test_publication_charges_one_point_and_refunds_failure(users, monkeypatch):
    from server import creator_tools, workbench
    first, second = users
    job = create_job(first, '/api/creator-tools/assets/tie-tu/a/remix-01.jpg', 'bill-copy')
    with accounts._connect() as connection:
        connection.execute('UPDATE wallets SET balance=5,trial_balance=5,bonus_balance=0,paid_balance=0 WHERE user_id=?', (first['id'],))
    monkeypatch.setattr(workbench, 'provider_overrides', lambda: nullcontext())
    monkeypatch.setattr(creator_tools, 'remix_publication_copy', lambda images: {'titles': ['一', '二', '三'], 'body': '正文', 'tags': ['标签']})
    before = accounts.wallet_summary(first['id'])['balance']
    with pytest.raises(HTTPException):
        main.regenerate_remix_publication(job['id'], request(second))
    assert accounts.wallet_summary(first['id'])['balance'] == before
    assert main.regenerate_remix_publication(job['id'], request(first))['points_charged'] == 1
    assert accounts.wallet_summary(first['id'])['balance'] == before - 1
    def fail(images): raise ValueError('generation failed')
    monkeypatch.setattr(creator_tools, 'remix_publication_copy', fail)
    with pytest.raises(HTTPException):
        main.regenerate_remix_publication(job['id'], request(first))
    assert accounts.wallet_summary(first['id'])['balance'] == before - 1
    with accounts._connect() as connection:
        records = connection.execute('SELECT feature,status FROM usage_records WHERE user_id=? AND path=? ORDER BY created_at', (first['id'], '/api/viral-remix/publication')).fetchall()
    assert [row['status'] for row in records] == ['completed', 'refunded']
    assert records[0]['feature'] == '爆款贴图标题与文案生成'
    with accounts._connect() as connection:
        connection.execute('UPDATE wallets SET balance=0,trial_balance=0,bonus_balance=0,paid_balance=0 WHERE user_id=?', (first['id'],))
    with pytest.raises(HTTPException) as insufficient:
        main.regenerate_remix_publication(job['id'], request(first))
    assert insufficient.value.status_code == 402
