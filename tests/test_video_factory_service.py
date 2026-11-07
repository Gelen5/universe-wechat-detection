import json
from pathlib import Path

from PIL import Image

from server.video_factory_mpt import ScenePlan
from server.video_factory_plan import VideoProject
from server.video_factory_service import build_bundle, load_or_build_plan


def _plan():
    return VideoProject(
        category='book',
        topic='曾国藩家书',
        duration_target=30,
        visual_style='chinese',
        title='一个人如何在喧闹里守住自己',
        cover_title='守住自己的节奏',
        scenes=[ScenePlan(
            sequence=1,
            narration='真正的自律并不喧闹，它只是每天把一件小事做稳。',
            duration_target=30,
            visual_prompt='书案、旧信与窗边微光',
            evidence_refs=['https://example.com/source'],
        )],
    )


def test_bundle_contains_all_acceptance_files_without_music(tmp_path, monkeypatch):
    monkeypatch.delenv('VIDEO_FACTORY_BGM_PATH', raising=False)
    Image.new('RGB', (1080, 1920), '#4b685a').save(tmp_path / 'scene-1.png')
    (tmp_path / 'final.mp4').write_bytes(b'fake-video')
    (tmp_path / 'captions.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n文案\n', encoding='utf-8')
    bundle = build_bundle(_plan(), tmp_path, {'content_review': 'needs_review'})
    assert set(bundle) == {
        'video', 'cover', 'captions', 'script', 'storyboard',
        'sources', 'quality', 'cost',
    }
    for path in bundle.values():
        assert Path(path).is_file()
        assert Path(path).stat().st_size > 0
    script = json.loads((tmp_path / 'script.json').read_text(encoding='utf-8'))
    assert script['cover_title'] == '守住自己的节奏'
    assert json.loads((tmp_path / 'sources.json').read_text(encoding='utf-8'))[0]['url'] == 'https://example.com/source'
    cost = json.loads((tmp_path / 'cost_report.json').read_text(encoding='utf-8'))
    assert cost['status'] == 'unknown'


def test_bundle_never_claims_commercial_rights(tmp_path):
    Image.new('RGB', (1080, 1920), '#4b685a').save(tmp_path / 'scene-1.png')
    (tmp_path / 'final.mp4').write_bytes(b'fake-video')
    (tmp_path / 'captions.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\n文案\n', encoding='utf-8')
    build_bundle(_plan(), tmp_path, {'content_review': 'needs_review'})
    sources = (tmp_path / 'sources.json').read_text(encoding='utf-8')
    quality = (tmp_path / 'quality_report.json').read_text(encoding='utf-8')
    assert '仍需逐条核验' in sources
    assert 'needs_review' in quality


def test_retry_reuses_the_first_plan(tmp_path, monkeypatch):
    calls = []

    def build(payload):
        calls.append(payload)
        return _plan()

    monkeypatch.setattr('server.video_factory_service.build_plan', build)
    first = load_or_build_plan({'topic': '第一次'}, tmp_path)
    second = load_or_build_plan({'topic': '第二次'}, tmp_path)
    assert first == second
    assert len(calls) == 1
