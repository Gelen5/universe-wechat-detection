import json
from types import SimpleNamespace
from server.video_factory_quality import inspect_video

def test_preflight_never_auto_approves_content(tmp_path, monkeypatch):
    p=tmp_path/'clip.mp4'; p.write_bytes(b'0'*11000)
    media={'streams':[{'codec_type':'video','width':1080,'height':1920},{'codec_type':'audio'}], 'format':{'duration':'30'}}
    monkeypatch.setattr('server.video_factory_quality.subprocess.run',lambda *a,**kw:SimpleNamespace(stdout=json.dumps(media)))
    report=inspect_video(p,30)
    assert report['metadata_checks_pass']
    assert report['content_review']=='needs_review'
    media['format']['duration']='10'
    assert not inspect_video(p,30)['metadata_checks_pass']

def test_subtitle_timing(tmp_path):
    from server.video_factory_quality import inspect_subtitles
    p=tmp_path/'x.srt'; p.write_text('1\n00:00:00,100 --> 00:00:01,000\nhello\n',encoding='utf8')
    assert inspect_subtitles(p,2)['timing_valid']
    assert not inspect_subtitles(p,0.5)['timing_valid']

def test_av_probe_result(tmp_path,monkeypatch):
    from server.video_factory_quality import inspect_av
    p=tmp_path/'clip.mp4';p.write_bytes(b'x')
    log='black_start:1.0 black_end:3.0 black_duration:2.0\nsilence_start: 4\nsilence_end: 7 | silence_duration: 3\n'
    monkeypatch.setattr('server.video_factory_quality.subprocess.run',lambda *a,**kw:SimpleNamespace(stderr=log,returncode=0))
    report=inspect_av(p)
    assert report['decode_ok'] and len(report['black_intervals'])==1 and len(report['silent_intervals'])==1
    assert report['content_review']=='needs_review'
