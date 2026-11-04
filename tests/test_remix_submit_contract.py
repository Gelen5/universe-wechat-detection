from types import SimpleNamespace
import pytest
from fastapi import HTTPException
import tests.support
from server import main,accounts,viral_remix_jobs,viral_remix_tasks,remix_design,remix_contract
from tests.test_remix_design import dataset


def setup(monkeypatch):
    analysis={'data_contract':dataset(),'ideas':remix_design.plans(dataset())}
    session={'conversation_skill':'viral-remix','result':analysis,'goal':'完整保留数据',
             'content_ledger':remix_contract.build(analysis,'完整保留数据')}
    monkeypatch.setattr(accounts,'require_user',lambda request:{'id':'owner'})
    monkeypatch.setattr(accounts,'load_workbench_session',lambda *args:session)
    return session


def test_submission_uses_server_dataset_and_exact_reservation_pages(monkeypatch):
    setup(monkeypatch);captured=[]
    def submit(uid,sid,idea):
        captured.append(idea)
        return {'id':'job','payload_json':'{}'}
    monkeypatch.setattr(viral_remix_jobs,'submit',submit)
    monkeypatch.setattr(viral_remix_tasks,'dispatch',lambda *args:None)
    main.generate_viral_remix_image(main.ViralRemixImageRequest(sessionId='valid-session',idea={'id':'A','data_contract':{'rows':[]}}),SimpleNamespace())
    assert len(captured[0]['data_contract']['rows'])==31
    assert len(captured[0]['cards'])==1
    assert captured[0]['source_fingerprint']


def test_textless_data_conflict_fails_before_reservation(monkeypatch):
    setup(monkeypatch)
    monkeypatch.setattr(viral_remix_jobs,'submit',lambda *args:pytest.fail('must not reserve points'))
    with pytest.raises(HTTPException) as exc:
        main.generate_viral_remix_image(main.ViralRemixImageRequest(sessionId='valid-session',idea={'id':'A','choices':{'textMode':'整组无字'}}),SimpleNamespace())
    assert exc.value.status_code==422
