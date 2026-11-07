"""Isolated MoneyPrinterTurbo adapter; not wired to public routes or billing.

Tested against MoneyPrinterTurbo 8b0206be2c7977e3bc3cf25ff99a2adc3c9c65f9.
POST timeouts are deliberately not retried: MPT may have accepted the task.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlsplit, unquote
from uuid import UUID

import requests
from pydantic import BaseModel, Field


class ScenePlan(BaseModel):
    sequence: int = Field(ge=1, le=8)
    narration: str = Field(min_length=1, max_length=1200)
    duration_target: float = Field(gt=0, le=60)
    visual_prompt: str = Field(min_length=1, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list)
    asset_source: str = ""
    license_info: str = ""
    character_reference: str = ""


class BookVideoPlan(BaseModel):
    topic: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=120)
    cover_title: str = Field(min_length=1, max_length=60)
    scenes: list[ScenePlan] = Field(min_length=1, max_length=8)
    duration_target: int = Field(ge=30, le=60)
    voice_id: str = "zh-CN-XiaoxiaoNeural-Female"


class MptRenderer:
    def __init__(self, base_url: str, api_key: str, session=None):
        self.base_url = base_url.rstrip('/')
        self.session = session or requests.Session()
        self.session.headers.update({'x-api-key': api_key})

    def _request(self, method, path, **kwargs):
        response = self.session.request(method, self.base_url + '/api/v1' + path,
                                        timeout=(5, 30), allow_redirects=False, **kwargs)
        response.raise_for_status()
        if response.status_code != 200:
            raise RuntimeError('Unexpected renderer response status')
        payload = response.json()
        if payload.get('status') != 200 or not isinstance(payload.get('data'), dict):
            raise RuntimeError('Renderer returned an invalid response')
        return payload['data']

    def upload(self, path: Path) -> str:
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
            raise ValueError('Only local image materials are supported')
        with path.open('rb') as stream:
            result = self._request('POST', '/video_materials', files={'file': (path.name, stream)})
        filename = result.get('file', '')
        if not filename or filename != Path(filename).name or '/' in filename or '\\' in filename:
            raise RuntimeError('Renderer returned an invalid material name')
        return filename

    def render(self, plan: BookVideoPlan, material_names: list[str]) -> str:
        if len(plan.scenes) != 1:
            raise NotImplementedError('MPT does not preserve scene narration timing')
        if not material_names or len(material_names) != len(plan.scenes):
            raise ValueError('Each scene must have one uploaded image')
        if any(name != Path(name).name or '/' in name or '\\' in name for name in material_names):
            raise ValueError('Invalid renderer material name')
        payload = {'video_subject': plan.topic, 'video_script': '\n'.join(s.narration for s in plan.scenes),
                   'video_source': 'local', 'video_materials': [{'provider': 'local', 'url': name} for name in material_names],
                   'video_aspect': '9:16', 'video_concat_mode': 'sequential', 'image_motion': 'zoom',
                   'match_materials_to_script': True, 'voice_name': plan.voice_id, 'subtitle_enabled': True,
                   'video_count': 1, 'n_threads': 2, 'bgm_type': 'none'}
        return str(UUID(self._request('POST', '/videos', json=payload)['task_id']))

    def get_status(self, task_id: str) -> dict:
        task_id = str(UUID(task_id))
        data = self._request('GET', '/tasks/' + quote(task_id, safe=''))
        state = {-1: 'failed', 1: 'succeeded', 4: 'running'}.get(data.get('state'), 'unknown')
        return {'state': state, 'progress': data.get('progress', 0), 'data': data}

    def get_result(self, task_id: str, target: Path, max_bytes: int = 200 * 1024 * 1024) -> None:
        task_id = str(UUID(task_id))
        status = self.get_status(task_id)
        videos = status['data'].get('videos') or []
        if status['state'] != 'succeeded' or len(videos) != 1:
            raise RuntimeError('Renderer has no finished video')
        parsed = urlsplit(videos[0])
        expected = f'/tasks/{task_id}/'
        path = unquote(parsed.path)
        if not path.startswith(expected) or '/' in path[len(expected):] or not path.endswith('.mp4'):
            raise RuntimeError('Renderer returned an invalid result path')
        # Ignore a configured external endpoint in MPT output; fetch only from
        # the trusted service origin, never from an arbitrary returned URL.
        with self.session.get(self.base_url + quote(path, safe='/'), timeout=(5, 120),
                              allow_redirects=False, stream=True) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise RuntimeError('Unexpected renderer download status')
            written = 0
            try:
                with target.open('xb') as output:
                    for chunk in response.iter_content(1024 * 1024):
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError('Renderer output exceeds size limit')
                        output.write(chunk)
            except FileExistsError:
                raise
            except Exception:
                target.unlink(missing_ok=True)
                raise

    def create_narration(self, text: str, voice_id: str, rate: float = 1.0) -> str:
        if not 0.7 <= rate <= 1.3:
            raise ValueError('配音语速超出可用范围')
        if not text.strip() or len(text) > 1200:
            raise ValueError('旁白长度无效')
        result = self._request('POST', '/subtitle', json={'video_script': text,
                               'voice_name': voice_id, 'voice_rate': rate,
                               'subtitle_enabled': True, 'bgm_type': 'none'})
        return str(UUID(result['task_id']))

    def narration_result(self, task_id: str, audio: Path, subtitles: Path) -> None:
        task_id = str(UUID(task_id))
        status = self.get_status(task_id)
        if status['state'] != 'succeeded':
            raise RuntimeError('旁白任务尚未完成')
        uri = status['data'].get('subtitle_path') or ''
        if unquote(urlsplit(uri).path) != f'/tasks/{task_id}/subtitle.srt':
            raise RuntimeError('旁白字幕地址无效')
        if audio.exists() or subtitles.exists():
            raise FileExistsError('旁白输出已存在')
        created = []
        try:
            for filename, target, max_bytes in [('audio.mp3', audio, 20_000_000),
                                                 ('subtitle.srt', subtitles, 1_000_000)]:
                with self.session.get(self.base_url + f'/tasks/{task_id}/{filename}',
                                      timeout=(5, 60), allow_redirects=False, stream=True) as response:
                    response.raise_for_status()
                    if response.status_code != 200: raise RuntimeError('旁白下载状态错误')
                    written = 0
                    with target.open('xb') as f:
                        created.append(target)
                        for chunk in response.iter_content(1024 * 1024):
                            written += len(chunk)
                            if written > max_bytes: raise ValueError('旁白文件过大')
                            f.write(chunk)
        except Exception:
            for target in created: target.unlink(missing_ok=True)
            raise

    def cancel(self, task_id: str) -> None:
        # MPT DELETE destroys completed results and refuses running tasks: it is
        # not a cancellation API. Never claim cancellation or delete artifacts.
        raise NotImplementedError('MoneyPrinterTurbo cannot cancel an active task')
