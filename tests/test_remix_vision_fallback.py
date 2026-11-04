import json
from unittest.mock import Mock
import pytest
import requests
from server import creator_tools as tools


def response(payload):
    result=Mock()
    result.json.return_value={'choices':[{'message':{'content':json.dumps(payload)}}]}
    return result


@pytest.mark.parametrize('failure',[requests.Timeout('upstream timeout'),requests.HTTPError(response=Mock(status_code=504))])
def test_real_image_body_is_reused_by_one_fallback(monkeypatch,failure):
    monkeypatch.setattr(tools.workbench,'_api_url',lambda *args:'https://test.invalid')
    monkeypatch.setattr(tools.workbench,'_headers',lambda *args:{})
    payload={'ideas':[{'id':x} for x in 'ABC'],'visual_contract':{'asset_type':'poster'}}
    calls=[]
    def post(*args,**kwargs):
        calls.append(kwargs)
        if len(calls)==1:raise failure
        return response(payload)
    monkeypatch.setattr(tools.requests,'post',post)
    body={'model':'gpt-6.1-terra','messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'private-reference'}}]}]}
    data,used=tools._remix_vision(body)
    assert used=='gpt-6.1-sol' and data==payload
    assert len(calls)==2
    assert calls[0]['json']['messages']==calls[1]['json']['messages']
    assert calls[0]['json']['reasoning_effort']=='low'
    assert calls[0]['timeout'][1]==65
    assert body['model']=='gpt-6.1-terra'


def test_both_services_fail_without_an_infinite_retry(monkeypatch):
    monkeypatch.setattr(tools.workbench,'_api_url',lambda *args:'https://test.invalid')
    monkeypatch.setattr(tools.workbench,'_headers',lambda *args:{})
    post=Mock(side_effect=requests.Timeout())
    monkeypatch.setattr(tools.requests,'post',post)
    with pytest.raises(tools.workbench.ProviderError,match='备用视觉服务'):
        tools._remix_vision({'model':'gpt-6.1-terra','messages':[]})
    assert post.call_count==2


def test_invalid_plan_falls_back_instead_of_delivering_partial_results(monkeypatch):
    monkeypatch.setattr(tools.workbench,'_api_url',lambda *args:'https://test.invalid')
    monkeypatch.setattr(tools.workbench,'_headers',lambda *args:{})
    valid={'ideas':[{'id':x} for x in 'ABC'],'visual_contract':{'asset_type':'poster'}}
    post=Mock(side_effect=[response({'ideas':[{'id':'A'}]}),response(valid)])
    monkeypatch.setattr(tools.requests,'post',post)
    assert tools._remix_vision({'model':'gpt-6.1-terra','messages':[]})==(valid,'gpt-6.1-sol')
