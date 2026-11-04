import json
from contextlib import nullcontext
import pytest
import tests.support
from server import viral_remix_tasks as tasks,remix_quality


@pytest.mark.parametrize('accepted',[True,False])
def test_one_repair_does_not_charge_twice(monkeypatch,tmp_path,accepted):
    idea={'content_ledger':{'version':2},'id':'A'}
    job={'id':'qa-job','payload_json':json.dumps({'idea':idea,'session_id':'qa','count':1})}
    monkeypatch.setattr(tasks.accounts,'claim_job',lambda *args:job)
    monkeypatch.setattr(tasks.workbench,'provider_overrides',lambda:nullcontext())
    monkeypatch.setattr(tasks.creator_tools,'prepare_remix_cards',lambda *args:([{}],idea,tmp_path/'draft'))
    calls=[];settlements=[];statuses=[]
    def generate(*args):
        calls.append(args)
        return {'url':'/qa.jpg','index':1}
    monkeypatch.setattr(tasks.creator_tools,'generate_remix_card',generate)
    reports=iter([{'passed':False,'issues':['文字裁切'],'repair':'缩小文字'},
                  {'passed':accepted,'issues':[] if accepted else ['文字仍裁切'],'repair':''}])
    monkeypatch.setattr(remix_quality,'inspect_image',lambda *args:next(reports))
    monkeypatch.setattr(tasks.accounts,'progress_job',lambda *args,**kwargs:statuses.append(kwargs['stage']))
    monkeypatch.setattr(tasks.accounts,'finish_job',lambda *args:None)
    monkeypatch.setattr(tasks.accounts,'fail_job',lambda *args:None)
    monkeypatch.setattr(tasks.jobs,'settle',lambda job,images,elapsed:settlements.append(images))
    result=tasks.run.run('qa-job')
    assert len(calls)==2
    assert len(settlements)==1
    assert len(settlements[0])==(1 if accepted else 0)
    assert 'repairing' in statuses
    assert result['status']==('succeeded' if accepted else 'failed')
