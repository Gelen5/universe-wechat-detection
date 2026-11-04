import base64
import io
import uuid
from types import SimpleNamespace
import pytest
from PIL import Image
from fastapi import HTTPException
import tests.support
from server import accounts,remix_studio_api as api


@pytest.fixture
def actor(monkeypatch):
    accounts.init_db()
    user=accounts.create_user(uuid.uuid4().hex+'@example.test','password123','Studio QA')
    with accounts._connect() as db:
        db.execute('UPDATE wallets SET balance=100,trial_balance=100 WHERE user_id=?',(user['id'],))
    monkeypatch.setattr(accounts,'require_user',lambda request:user)
    monkeypatch.setattr(api.tasks,'dispatch',lambda job_id:None)
    return user


def payload():
    buffer=io.BytesIO();Image.new('RGB',(90,120),'green').save(buffer,format='PNG')
    return api.Create(imageData='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode(),requestId=uuid.uuid4().hex)


def test_create_replay_returns_same_job_without_double_charge(actor):
    request=payload();before=accounts.wallet_summary(actor['id'])['balance']
    first=api.create(request,SimpleNamespace())['job']
    second=api.create(request,SimpleNamespace())['job']
    assert first['id']==second['id']
    assert first['total']==1
    assert accounts.wallet_summary(actor['id'])['balance']==before-2
    assert 'reference' not in str(first)


def test_revise_preserves_parent_and_is_owner_scoped(actor,monkeypatch):
    parent=api.create(payload(),SimpleNamespace())['job']
    accounts.claim_job(['image'],parent['id'])
    accounts.finish_job(parent['id'],{'images':[{'url':'/example.jpg','index':1}],'design':{'headline':'原标题'}})
    revision=api.revise(parent['id'],api.Revise(goal='只加强标题',options=['headline'],requestId=uuid.uuid4().hex),SimpleNamespace())['job']
    assert revision['parent_id']==parent['id']
    assert accounts.job(parent['id'],actor['id'])['status']=='succeeded'
    assert len(api.history(SimpleNamespace())['jobs'])==2
    monkeypatch.setattr(accounts,'require_user',lambda request:{'id':'other-user'})
    with pytest.raises(HTTPException) as exc: api.status(parent['id'],SimpleNamespace())
    assert exc.value.status_code==404


def test_empty_revision_and_unreadable_source_fail_before_charge(actor):
    before=accounts.wallet_summary(actor['id'])['balance']
    request=payload();request.imageData='data:image/png;base64,YmFk'
    with pytest.raises(HTTPException) as exc: api.create(request,SimpleNamespace())
    assert exc.value.status_code==422
    assert accounts.wallet_summary(actor['id'])['balance']==before
