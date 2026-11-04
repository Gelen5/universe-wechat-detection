import uuid
from types import SimpleNamespace
import pytest
import tests.support
from fastapi import HTTPException
from server import accounts,main,remix_contract,remix_design
from tests.test_remix_design import dataset


def test_correction_retains_prior_ledger_and_blocks_stale_update(monkeypatch):
    accounts.init_db()
    user=accounts.create_user(uuid.uuid4().hex+'@example.test','password123','QA')
    monkeypatch.setattr(accounts,'require_user',lambda request:user)
    analysis={'data_contract':dataset(),'ideas':remix_design.plans(dataset())}
    ledger=remix_contract.build(analysis,'完整保留数据')
    session_id=uuid.uuid4().hex
    accounts.save_workbench_session(user['id'],{'id':session_id,'conversation_skill':'viral-remix',
        'result':analysis,'content_ledger':ledger,'goal':'完整保留数据'})
    changed=dataset(); changed['rows'][0]['value']='29.4'
    payload=main.RemixDataCorrection(dataset=changed,fingerprint=ledger['fingerprint'])
    result=main.correct_remix_data(session_id,payload,SimpleNamespace())
    assert result['result']['data_contract']['rows'][0]['value']=='29.4'
    saved=accounts.load_workbench_session(session_id,user['id'])
    assert saved['ledger_history'][0]['data']['rows'][0]['value']=='29.3'
    assert saved['content_ledger']['fingerprint']!=ledger['fingerprint']
    with pytest.raises(HTTPException) as exc: main.correct_remix_data(session_id,payload,SimpleNamespace())
    assert exc.value.status_code==409
