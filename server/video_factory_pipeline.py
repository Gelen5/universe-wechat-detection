"""Isolated checkpointed pipeline; no public API or production billing registration.

A paid call whose outcome is unknown is never submitted again automatically.
The caller must serialize execution for each project and supply an image provider.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
from .video_factory_plan import VideoProject
from .video_factory_scene_renderer import SceneAsset, render_scenes
from .video_factory_quality import inspect_video, inspect_subtitles


class PendingTask(RuntimeError):
    """Raised when a remote TTS call is accepted but not finished yet."""

    def __init__(self, message: str, retry_after: int = 10):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class UnknownProviderOutcome(RuntimeError):
    pass


def _save(path: Path, data: dict) -> None:
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w',encoding='utf8') as f:
        json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def run_project(plan: VideoProject, directory: Path, renderer, image_generator, *,
                target_seconds: int | None = None) -> dict:
    """Resume one project from completed images and persisted narration task IDs.

    image_generator(scene, output_path, idempotency_key) must write one image and
    must not retry an ambiguous paid request. It is intentionally dependency-injected.
    """
    directory.mkdir(parents=True,exist_ok=True)
    fingerprint=hashlib.sha256(plan.model_dump_json().encode()).hexdigest()
    path=directory/'checkpoint.json'
    lock=directory/'.pipeline.lock'
    try:
        descriptor=os.open(str(lock),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc:
        raise RuntimeError('项目正在处理或锁需要人工检查') from exc
    try:
        os.close(descriptor)
        state=json.loads(path.read_text(encoding='utf8')) if path.exists() else {'fingerprint':fingerprint,'scenes':{}}
        if state.get('fingerprint') != fingerprint: raise ValueError('项目内容已变化，不能复用检查点')
        _save(path,state)
        assets=[]
        for scene in plan.scenes:
            key=str(scene.sequence); info=state['scenes'].setdefault(key,{})
            image=directory/f'scene-{key}.png';audio=directory/f'audio-{key}.mp3';subs=directory/f'subtitle-{key}.srt'
            if not info.get('image_done'):
                if info.get('image_inflight'):raise UnknownProviderOutcome('生图结果未知，需查单后恢复')
                info['image_inflight']=True;_save(path,state)
                image_generator(scene,image,f'{fingerprint}:image:{key}')
                if not image.is_file() or image.stat().st_size==0: raise ValueError('生图结果无效')
                info.update(image_done=True,image_inflight=False);_save(path,state)
            elif not image.is_file():raise ValueError('已保存的图片缺失，不能自动重复生图')
            if not info.get('narration_done'):
                task=info.get('narration_task')
                if not task:
                    if info.get('narration_inflight'):raise UnknownProviderOutcome('配音任务结果未知，需查单后恢复')
                    info['narration_inflight']=True;_save(path,state)
                    task=renderer.create_narration(scene.narration,plan.voice_id)
                    info.update(narration_task=task,narration_inflight=False);_save(path,state)
                status=renderer.get_status(task)
                if status['state']=='running':
                    raise PendingTask('配音任务仍在进行', retry_after=3)
                if status['state']!='succeeded':raise RuntimeError('配音任务未成功，需人工检查')
                if audio.exists() or subs.exists():raise UnknownProviderOutcome('配音文件不完整，需人工核对')
                renderer.narration_result(task,audio,subs)
                info['narration_done']=True;_save(path,state)
            elif not audio.is_file() or not subs.is_file():raise ValueError('已保存的配音或字幕缺失')
            assets.append(SceneAsset(image,audio,subs))
        video=directory/'final.mp4';captions=directory/'captions.srt'
        if not state.get('render_done'):
            if video.exists() or captions.exists():raise UnknownProviderOutcome('渲染输出状态不明，需人工检查')
            render_scenes(assets,video,captions,target_seconds=target_seconds or plan.duration_target)
            state['render_done']=True;_save(path,state)
        if not video.is_file() or not captions.is_file():raise ValueError('已保存的成片缺失')
        report=inspect_video(video,target_seconds or plan.duration_target)
        report['subtitle']=inspect_subtitles(captions,report['duration_seconds'])
        report['content_review']='needs_review'
        _save(directory/'quality_report.json',report)
        return report
    finally:
        lock.unlink(missing_ok=True)
