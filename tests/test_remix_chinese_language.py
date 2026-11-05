from unittest.mock import patch
from contextlib import nullcontext
import json
import pytest
import tests.support
from server import creator_tools, viral_remix_tasks as tasks, remix_quality, image_provider


def test_chinese_prompt_prohibits_translation_and_decorative_english(tmp_path):
    from tests.test_remix_generation_retry import image_result
    with patch.object(image_provider,'generate',return_value=image_result()) as generate:
        creator_tools.generate_remix_card({}, {'headline':'合同到期不续签，补偿要看哪些条件？'},1,1,tmp_path)
    prompt=generate.call_args.args[0]['prompt']
    assert '不要把中文翻译成英文' in prompt
    assert '合同、文件或背景里编造英文条款' in prompt


def test_language_policy_respects_no_text_and_explicit_english():
    page={'headline':'中文标题'}
    assert not creator_tools.remix_chinese_text_required({'text_policy':'all_no_text'},page,1)
    assert not creator_tools.remix_chinese_text_required({'user_goal':'请做英文版'},page,1)
    assert creator_tools.remix_chinese_text_required({'user_goal':'不要英文'},page,1)


@pytest.mark.parametrize('outcome',['pass','fail','error'])
def test_language_repair_once_preserves_original_on_failure(monkeypatch,tmp_path,outcome):
    idea={'content_ledger':{'version':2},'headline':'合同到期不续签'}
    page={'headline':'合同到期不续签'}
    original={'url':'/original.jpg','index':1}
    original_file=tmp_path/'remix-01.jpg'; original_file.write_bytes(b'original')
    calls=[]
    def generate(idea,page,index,total,directory):
        calls.append(page)
        if outcome=='error': raise RuntimeError('unavailable')
        (directory/'remix-01.jpg').write_bytes(b'repaired')
        return {'url':'/temporary.jpg','index':1}
    monkeypatch.setattr(tasks.creator_tools,'generate_remix_card',generate)
    monkeypatch.setattr(tasks.accounts,'progress_job',lambda *a,**k:None)
    monkeypatch.setattr(remix_quality,'inspect_image',lambda *a,**k:{'passed':outcome=='pass','issues':[] if outcome=='pass' else ['英文仍然存在'],'repair':''})
    report={'passed':False,'issues':['海报文字为英文，未呈现中文核心问题'],'repair':''}
    image,result,retried=tasks._retry_wrong_language(original,report,idea,page,1,1,tmp_path,'job',[])
    assert retried and len(calls)==1
    assert '不要翻译成英文' in calls[0]['repair_instruction']
    assert original_file.read_bytes()==(b'repaired' if outcome=='pass' else b'original')
    assert image['url']=='/original.jpg'
    assert result['passed']==(outcome=='pass')


def test_unrelated_review_issue_does_not_trigger_retry(monkeypatch,tmp_path):
    monkeypatch.setattr(tasks.creator_tools,'generate_remix_card',lambda *a,**k:pytest.fail('unexpected retry'))
    image,report,retried=tasks._retry_wrong_language({'url':'/x'}, {'passed':False,'issues':['年龄可能不一致']}, {'headline':'中文'}, {'headline':'中文'},1,1,tmp_path,'job',[])
    assert not retried

def test_language_repair_in_job_keeps_single_image_charge(monkeypatch, tmp_path):
    idea={'content_ledger':{'version':2},'headline':'合同到期不续签'}
    job={'id':'language-qa','user_id':'test','payload_json':json.dumps({'idea':idea,'session_id':'qa','count':1})}
    monkeypatch.setattr(tasks.accounts,'claim_job',lambda *args:job)
    monkeypatch.setattr(tasks.workbench,'provider_overrides',lambda:nullcontext())
    monkeypatch.setattr(tasks.creator_tools,'prepare_remix_cards',lambda *args:([{'headline':'中文标题'}],idea,tmp_path/'draft'))
    calls=[];settlements=[];finished=[]
    def generate(idea,page,index,total,directory):
        calls.append(page)
        (directory/'remix-01.jpg').write_bytes(b'retry' if len(calls)>1 else b'original')
        return {'url':'/original.jpg','index':1}
    monkeypatch.setattr(tasks.creator_tools,'generate_remix_card',generate)
    reports=iter([{'passed':False,'issues':['海报文字为英文'],'repair':''},{'passed':True,'issues':[],'repair':''}])
    monkeypatch.setattr(remix_quality,'inspect_image',lambda *a,**k:next(reports))
    monkeypatch.setattr(tasks.accounts,'progress_job',lambda *a,**k:None)
    monkeypatch.setattr(tasks.accounts,'finish_job',lambda job_id,result:finished.append(result))
    monkeypatch.setattr(tasks.accounts,'fail_job',lambda *a:pytest.fail('unexpected failure'))
    monkeypatch.setattr(tasks.jobs,'settle',lambda job,images,elapsed:settlements.append(images))
    result=tasks.run.run('language-qa')
    assert result['status']=='succeeded'
    assert len(calls)==2 and len(settlements)==1 and len(settlements[0])==1
    assert finished[0]['images'][0]['check_passed'] is True
    assert (tmp_path/'remix-language-qa'/'remix-01.jpg').read_bytes()==b'retry'
