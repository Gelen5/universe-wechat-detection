from pathlib import Path
import pytest
from pydantic import ValidationError
from server.video_factory_mpt import BookVideoPlan, MptRenderer, ScenePlan

class Response:
    def __init__(self, data): self.data=data
    status_code=200
    def raise_for_status(self): pass
    def json(self): return {'status':200,'data':self.data}

class Session:
    def __init__(self): self.headers={}; self.calls=[]
    def request(self, method, url, **kwargs):
        self.calls.append((method,url,kwargs))
        if url.endswith('/videos'): return Response({'task_id':'7deb84db-7c4d-456f-8c88-ba58475f3718'})
        if url.endswith('/video_materials'): return Response({'file':'abc.png'})
        return Response({'state':1,'progress':100,'videos':[]})

def test_book_contract_and_renderer(tmp_path):
    scene=ScenePlan(sequence=1,narration='读书',duration_target=30,visual_prompt='书页')
    plan=BookVideoPlan(topic='读书',title='读书',cover_title='读书',duration_target=30,scenes=[scene])
    session=Session(); renderer=MptRenderer('http://localhost:17865','secret',session)
    image=tmp_path/'book.png'; image.write_bytes(b'image')
    assert renderer.upload(image)=='abc.png'
    task=renderer.render(plan,['abc.png'])
    assert renderer.get_status(task)['state']=='succeeded'
    assert session.calls[1][2]['json']['video_script']=='读书'
    assert session.calls[1][2]['json']['video_source']=='local'
    with pytest.raises(ValueError): renderer.render(plan,['../other.png'])
    with pytest.raises(NotImplementedError): renderer.cancel(task)
    with pytest.raises(ValidationError): BookVideoPlan(topic='',title='a',cover_title='a',duration_target=30,scenes=[scene])

def test_result_rejects_untrusted_path(tmp_path):
    class Unsafe(Session):
        def request(self, method, url, **kwargs):
            return Response({'state':1,'progress':100,'videos':['http://evil.example/tasks/other/final.mp4']})
    r=MptRenderer('http://localhost:17865','secret',Unsafe())
    with pytest.raises(RuntimeError, match='invalid result path'):
        r.get_result('7deb84db-7c4d-456f-8c88-ba58475f3718',tmp_path/'out.mp4')
