import pytest
from server.video_factory_plan import make_plan

@pytest.mark.parametrize('category', ['book','history','folklore','china'])
def test_four_categories_share_contract(category):
    source={'url':'https://example.test/source','summary':'经过人工审核的资料'}
    obj={'category':category,'topic':'测试','duration_target':30,'visual_style':'auto','title':'标题','cover_title':'封面','scenes':[{'sequence':1,'narration':'介绍'*60,'duration_target':30,'visual_prompt':'场景','evidence_refs':[source['url']]}]}
    assert make_plan(category,'测试',30,'auto',[source],lambda _:obj).category==category
    obj['scenes'][0]['evidence_refs']=['https://other.test/']
    bound = make_plan(category,'测试',30,'auto',[source],lambda _:obj)
    assert bound.scenes[0].evidence_refs == [source['url']]


def test_plan_rejects_too_many_short_scenes():
    source={'url':'https://example.test/source','summary':'经过人工审核的资料'}
    scenes = [
        {'sequence':i,'narration':'这是一个完整的中文句子。'*2,
         'duration_target':4,'visual_prompt':'场景','evidence_refs':[source['url']]}
        for i in range(1, 8)
    ]
    obj={'category':'book','topic':'测试','duration_target':30,'visual_style':'auto',
         'title':'标题','cover_title':'封面','scenes':scenes}
    with pytest.raises(ValueError, match='最多使用 6 个镜头'):
        make_plan('book','测试',30,'auto',[source],lambda _:obj)


def test_request_contract_overrides_model_prose():
    source={'url':'https://example.test/source','summary':'经过人工审核的资料'}
    obj={'category':'book','topic':'测试','duration_target':30,'visual_style':'中式水墨自由文本',
         'title':'标题','cover_title':'封面','scenes':[{
             'sequence':1,'narration':'介绍'*60,'duration_target':30,
             'visual_prompt':'场景','evidence_refs':[source['url']],
         }]}
    plan = make_plan('book','测试',30,'chinese',[source],lambda _:obj)
    assert plan.visual_style == 'chinese'


def test_object_reference_is_serialized_without_losing_sources():
    source={'url':'https://example.test/source','summary':'经过人工审核的资料'}
    obj={'category':'book','topic':'测试','duration_target':30,'visual_style':'auto',
         'title':'标题','cover_title':'封面',
         'character_reference':{'name':'人物','description':'统一服饰'},
         'scenes':[{
             'sequence':1,'narration':'介绍'*60,'duration_target':30,
             'visual_prompt':'场景','evidence_refs':[source['url']],
             'character_reference':{'name':'人物'},
         }]}
    plan = make_plan('book','测试',30,'auto',[source],lambda _:obj)
    assert '统一服饰' in plan.character_reference
    assert '人物' in plan.scenes[0].character_reference
    assert plan.scenes[0].evidence_refs == [source['url']]


def test_single_source_is_bound_when_model_rewrites_url():
    source={'url':'https://example.test/source','summary':'经过人工审核的资料'}
    obj={'category':'book','topic':'测试','duration_target':30,'visual_style':'auto',
         'title':'标题','cover_title':'封面','scenes':[{
             'sequence':1,'narration':'介绍'*60,'duration_target':30,
             'visual_prompt':'场景','evidence_refs':['https://example.test/changed'],
         }]}
    plan = make_plan('book','测试',30,'auto',[source],lambda _:obj)
    assert plan.scenes[0].evidence_refs == [source['url']]


def test_multiple_sources_still_require_exact_evidence():
    sources=[
        {'url':'https://example.test/one','summary':'经过人工审核的资料一'},
        {'url':'https://example.test/two','summary':'经过人工审核的资料二'},
    ]
    obj={'category':'book','topic':'测试','duration_target':30,'visual_style':'auto',
         'title':'标题','cover_title':'封面','scenes':[{
             'sequence':1,'narration':'介绍'*60,'duration_target':30,
             'visual_prompt':'场景','evidence_refs':['https://example.test/changed'],
         }]}
    with pytest.raises(ValueError, match='来源'):
        make_plan('book','测试',30,'auto',sources,lambda _:obj)
