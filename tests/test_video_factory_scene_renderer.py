from pathlib import Path
import subprocess
from PIL import Image
from server.video_factory_scene_renderer import SceneAsset, render_scenes
from server.video_factory_quality import inspect_subtitles

def test_real_ffmpeg_preserves_scene_order(tmp_path):
    scenes=[]
    for i,color in enumerate(('red','blue')):
        image=tmp_path/f'{i}.png';Image.new('RGB',(180,320),color).save(image)
        audio=tmp_path/f'{i}.mp3'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',f'sine=frequency={400+i*100}:duration=1','-q:a','8',str(audio)],check=True)
        subtitle=tmp_path/f'{i}.srt';subtitle.write_text(f'1\n00:00:00,100 --> 00:00:00,800\nscene {i}\n',encoding='utf8')
        scenes.append(SceneAsset(image,audio,subtitle))
    output=tmp_path/'final.mp4'; captions=tmp_path/'captions.srt'
    durations=render_scenes(scenes,output,captions,width=180,height=320,target_seconds=2)
    assert output.stat().st_size>1000
    assert inspect_subtitles(captions,sum(durations))['count']==2
    assert captions.read_text(encoding='utf8').index('scene 0') < captions.read_text(encoding='utf8').index('scene 1')
    subprocess.run(['ffmpeg','-v','error','-i',str(output),'-f','null','-'],check=True)
    for second, expected in ((0.3,'red'),(1.4,'blue')):
        frame=tmp_path/f'{expected}.png'
        subprocess.run(['ffmpeg','-v','error','-ss',str(second),'-i',str(output),'-frames:v','1',str(frame)],check=True)
        r,g,b=Image.open(frame).convert('RGB').getpixel((90,100))
        assert (r>b) if expected=='red' else (b>r)

def test_measured_duration_must_match_target():
    import pytest
    from server.video_factory_scene_renderer import validate_narration_duration
    validate_narration_duration([15,15],30)
    with pytest.raises(ValueError):validate_narration_duration([18,20],60)

def test_background_music_rejects_unsafe_volume(tmp_path):
    import pytest
    from server.video_factory_scene_renderer import mix_background_music
    with pytest.raises(ValueError):mix_background_music(tmp_path/'x',tmp_path/'y',tmp_path/'z',volume=0.5)
