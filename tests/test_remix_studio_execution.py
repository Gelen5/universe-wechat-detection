import io,json
from contextlib import nullcontext
from PIL import Image
import pytest
import tests.support
from server import accounts,creator_tools,image_provider,remix_studio as studio,viral_remix_jobs as jobs,workbench


@pytest.mark.parametrize('passed',[True,False])
def test_single_result_and_bounded_repair_settlement(monkeypatch,tmp_path,passed):
    job={'id':'studio-qa','user_id':'owner','payload_json':json.dumps({'idea':{'studio':{'reference':'source','options':[],'goal':'更抓眼球'}}})}
    design={'source':{'kind':'poster','facts':['原始事实']},'design':{'layout':'left','scene':'studio','difference':'new hierarchy'}}
    monkeypatch.setattr(studio,'plan',lambda *args:design)
    monkeypatch.setattr(creator_tools,'OUTPUT_DIR',tmp_path)
    monkeypatch.setattr(workbench,'provider_overrides',lambda:nullcontext())
    buffer=io.BytesIO();Image.new('RGB',(600,800),'green').save(buffer,format='PNG')
    monkeypatch.setattr(creator_tools,'_decode_image',lambda result:buffer.getvalue())
    calls=[]
    monkeypatch.setattr(image_provider,'generate',lambda request:calls.append(request) or {})
    reports=iter([{'passed':False,'issues':['标题偏小'],'repair':'增大标题'}, {'passed':passed,'issues':[] if passed else ['仍不清晰'],'repair':''}])
    monkeypatch.setattr(studio,'inspect',lambda *args:next(reports))
    monkeypatch.setattr(accounts,'progress_job',lambda *args,**kwargs:None)
    finished=[];failed=[];settled=[]
    monkeypatch.setattr(accounts,'finish_job',lambda job,result:finished.append(result))
    monkeypatch.setattr(accounts,'fail_job',lambda *args:failed.append(args))
    monkeypatch.setattr(jobs,'settle',lambda job,images,elapsed:settled.append(images))
    result=studio.execute(job)
    assert len(calls)==2
    assert len(settled)==1 and len(settled[0])==(1 if passed else 0)
    assert result['status']==('succeeded' if passed else 'failed')
    assert calls[1]['reference_image'].startswith('data:image/jpeg;base64,')
    if passed:
        assert finished[0]['source']==design['source']
        assert len(finished[0]['images'])==1
    else: assert failed
