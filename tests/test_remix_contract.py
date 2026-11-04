import pytest
from server import remix_contract


def test_selection_uses_server_facts_and_plan():
    session={'goal':'不要改五官','preserve_person':True,'result':{
        'content_type':'person_photo','content_core':{'facts':['原始事实']},
        'ideas':[{'id':'A','headline':'服务端标题','layout':'侧边排版'}]}}
    result=remix_contract.select(session,{'id':'A','headline':'篡改','content_ledger':{'core':{}},'choices':{'emotion':'被点醒'}})
    assert result['headline']=='服务端标题'
    assert result['content_ledger']['core']['facts']==['原始事实']
    assert result['content_ledger']['preserve_person']
    assert result['source_fingerprint']==remix_contract.build(session['result'],session['goal'],True)['fingerprint']


def test_unknown_plan_is_rejected():
    with pytest.raises(ValueError): remix_contract.select({'result':{'ideas':[]}},{'id':'A'})


def test_tutorial_coverage_rejects_missing_duplicate_and_reordered_steps():
    ledger=remix_contract.build({'content_type':'tutorial','content_core':{'steps':['打开应用','输入内容','保存']}},'')
    ids=[item['id'] for item in ledger['items']]
    remix_contract.validate_coverage(ledger,[{'source_ids':ids[:2]},{'source_ids':ids[2:]}])
    for actual in (ids[:-1],list(reversed(ids)),ids+[ids[0]]):
        with pytest.raises(ValueError): remix_contract.validate_coverage(ledger,[{'source_ids':actual}])
