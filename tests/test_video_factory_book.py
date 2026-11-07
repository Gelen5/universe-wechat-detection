from server.video_factory_book import book_plan
import pytest

def test_book_plan_requires_evidence_and_valid_order():
    sources=[{'url':'https://example.test/book','summary':'一本书'}]
    plan={'topic':'书','title':'书','cover_title':'书','duration_target':30,'scenes':[{'sequence':1,'narration':'阅读','duration_target':30,'visual_prompt':'书页','evidence_refs':[sources[0]['url']]}]}
    assert book_plan('书',30,sources,lambda _:plan).scenes[0].sequence==1
    plan['scenes'][0]['evidence_refs']=['https://wrong.test']
    with pytest.raises(ValueError): book_plan('书',30,sources,lambda _:plan)
