import copy
import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
import tests.support  # noqa: F401
from fastapi import HTTPException

from server import accounts, article_visual, creator_tools, workbench


@pytest.fixture
def setup_job(monkeypatch, tmp_path):
    accounts.init_db()
    suffix = uuid.uuid4().hex
    user = accounts.create_user(f'article-{suffix}@example.com', 'password12345', 'creator')
    other = accounts.create_user(f'other-{suffix}@example.com', 'password12345', 'other')
    with accounts._connect() as connection:
        connection.execute('UPDATE wallets SET balance=5,trial_balance=5,bonus_balance=0,paid_balance=0 WHERE user_id=?', (user['id'],))
    directory = tmp_path / 'job1'
    directory.mkdir()
    (directory / 'cover.png').write_bytes(b'generated image')
    job = {'id': 'job1', 'user_id': user['id'], 'article': {},
           'plan': {'slots': [{'id': 'cover', 'form': 'cover'}, {'id': 'body', 'form': 'data'}]},
           'images': {'cover': {'file': 'cover.png'}}}
    stored = {'job': job}
    monkeypatch.setattr(article_visual, 'JOBS_DIR', tmp_path)
    monkeypatch.setattr(article_visual, '_read_job', lambda job_id: copy.deepcopy(stored['job']))
    monkeypatch.setattr(article_visual, '_write_job', lambda value: stored.update(job=copy.deepcopy(value)))
    monkeypatch.setattr(workbench, 'provider_overrides', lambda: nullcontext())
    return user, other, stored, directory


def request(user):
    return SimpleNamespace(state=SimpleNamespace(user=user))


def test_publication_charges_saves_and_rejects_other_user(setup_job, monkeypatch):
    user, other, stored, directory = setup_job
    seen = []
    publication = {'titles': ['标题一', '标题二', '标题三'], 'body': '正文', 'tags': ['标签']}
    monkeypatch.setattr(creator_tools, 'publication_copy_from_files', lambda files: (seen.extend(files) or publication))
    with pytest.raises(HTTPException) as denied:
        article_visual.generate_publication('job1', request(other))
    assert denied.value.status_code == 404
    assert accounts.wallet_summary(user['id'])['balance'] == 5
    assert article_visual.generate_publication('job1', request(user))['points_charged'] == 1
    assert seen == [directory / 'cover.png']
    assert stored['job']['publication'] == publication
    assert accounts.wallet_summary(user['id'])['balance'] == 4
    body = article_visual.PublicationBody(titles=['新标题', '二', '三'], body='修改正文', tags=['标签'])
    article_visual.save_publication('job1', body, request(user))
    assert stored['job']['publication']['body'] == '修改正文'
    assert accounts.wallet_summary(user['id'])['balance'] == 4
    body.titles[0] = '字' * 21
    with pytest.raises(HTTPException) as invalid:
        article_visual.save_publication('job1', body, request(user))
    assert invalid.value.status_code == 422


def test_failure_or_changed_image_refunds(setup_job, monkeypatch):
    user, _, stored, directory = setup_job
    def fail(files):
        raise RuntimeError('unavailable')
    monkeypatch.setattr(creator_tools, 'publication_copy_from_files', fail)
    with pytest.raises(HTTPException):
        article_visual.generate_publication('job1', request(user))
    assert accounts.wallet_summary(user['id'])['balance'] == 5
    def change(files):
        (directory / 'cover.png').write_bytes(b'new image')
        return {'titles': ['一', '二', '三'], 'body': '正文', 'tags': []}
    monkeypatch.setattr(creator_tools, 'publication_copy_from_files', change)
    with pytest.raises(HTTPException) as changed:
        article_visual.generate_publication('job1', request(user))
    assert changed.value.status_code == 409
    assert 'publication' not in stored['job']
    assert accounts.wallet_summary(user['id'])['balance'] == 5
