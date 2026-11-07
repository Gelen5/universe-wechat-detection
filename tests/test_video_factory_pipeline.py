import pytest
from server.video_factory_mpt import ScenePlan
from server.video_factory_plan import VideoProject
from server.video_factory_pipeline import run_project,PendingTask,UnknownProviderOutcome

class Narrator:
 def __init__(self):self.count=0;self.ready=False
 def create_narration(self,text,voice):self.count+=1;return 'task-1'
 def get_status(self,task):return {'state':'succeeded' if self.ready else 'running'}
 def narration_result(self,task,audio,subs):audio.write_bytes(b'audio');subs.write_text('srt')

def plan():
 return VideoProject(category='book',topic='书',duration_target=30,visual_style='auto',title='书',cover_title='书',scenes=[ScenePlan(sequence=1,narration='读书',duration_target=30,visual_prompt='书页')])

def test_resume_uses_existing_paid_calls(tmp_path,monkeypatch):
 n=Narrator();images=[]
 def generate(scene,target,key):images.append(key);target.write_bytes(b'image')
 with pytest.raises(PendingTask):run_project(plan(),tmp_path,n,generate)
 n.ready=True
 def render(assets,video,captions,**kwargs):video.write_bytes(b'video');captions.write_text('captions')
 monkeypatch.setattr('server.video_factory_pipeline.render_scenes',render)
 monkeypatch.setattr('server.video_factory_pipeline.inspect_video',lambda *a:{'duration_seconds':30})
 monkeypatch.setattr('server.video_factory_pipeline.inspect_subtitles',lambda *a:{'timing_valid':True})
 assert run_project(plan(),tmp_path,n,generate)['content_review']=='needs_review'
 run_project(plan(),tmp_path,n,generate)
 assert len(images)==1 and n.count==1

def test_ambiguous_image_call_never_auto_retries(tmp_path):
 n=Narrator();calls=[]
 def fail(scene,target,key):calls.append(key);raise TimeoutError('unknown')
 with pytest.raises(TimeoutError):run_project(plan(),tmp_path,n,fail)
 with pytest.raises(UnknownProviderOutcome):run_project(plan(),tmp_path,n,fail)
 assert len(calls)==1
