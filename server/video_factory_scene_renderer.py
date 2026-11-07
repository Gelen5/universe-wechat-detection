"""Small local scene renderer. Inputs must already be generated and authorized.

Each scene has its own actual narration audio and SRT; no timing is guessed from
LLM estimates. It has no network access, billing or public endpoint.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SceneAsset:
    image: Path
    audio: Path
    subtitles: Path


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, timeout=timeout)


def _duration(path: Path, ffprobe: str, cwd: Path) -> float:
    p = _run([ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of',
              'default=noprint_wrappers=1:nokey=1', str(path)], cwd, 30)
    value = float(p.stdout.decode().strip())
    if not 0 < value <= 60:
        raise ValueError('音频时长不在允许范围内')
    return value


def _timestamp(ms: int) -> str:
    h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def _merge_subtitles(scenes: list[SceneAsset], durations: list[float], output: Path) -> None:
    from .video_factory_quality import inspect_subtitles
    pattern = re.compile(r'(\d\d):(\d\d):(\d\d),(\d\d\d)\s+-->\s+(\d\d):(\d\d):(\d\d),(\d\d\d)')
    def milliseconds(parts):
        h, m, s, ms = map(int, parts)
        return ((h * 60 + m) * 60 + s) * 1000 + ms
    offset = 0.0; entries = []
    for scene, duration in zip(scenes, durations):
        if not inspect_subtitles(scene.subtitles, duration)['timing_valid']:
            raise ValueError('分镜字幕时间无效')
        for block in re.split(r'\n\s*\n', scene.subtitles.read_text(encoding='utf-8-sig').strip()):
            lines = block.splitlines(); match = pattern.fullmatch(lines[1].strip())
            start = milliseconds(match.groups()[:4]) + round(offset * 1000)
            end = milliseconds(match.groups()[4:]) + round(offset * 1000)
            entries.append(f'{len(entries)+1}\n{_timestamp(start)} --> {_timestamp(end)}\n' + '\n'.join(lines[2:]))
        offset += duration
    output.write_text('\n\n'.join(entries) + '\n', encoding='utf-8')


def render_scenes(scenes: list[SceneAsset], output: Path, captions: Path, *,
                  ffmpeg: str = 'ffmpeg', ffprobe: str = 'ffprobe',
                  width: int = 1080, height: int = 1920, target_seconds: int) -> list[float]:
    if not 1 <= len(scenes) <= 8: raise ValueError('分镜数量必须为 1 至 8')
    if output.exists() or captions.exists(): raise FileExistsError('输出文件已存在')
    if width < 2 or height < 2 or width % 2 or height % 2: raise ValueError('画幅尺寸无效')
    with tempfile.TemporaryDirectory(prefix='video-scenes-') as temp:
        work = Path(temp); names = []
        if any(not all(p.is_file() for p in (scene.image, scene.audio, scene.subtitles)) for scene in scenes):
            raise ValueError('分镜素材不存在')
        durations = [_duration(scene.audio.resolve(), ffprobe, work) for scene in scenes]
        if sum(durations) > 65: raise ValueError('总时长超过限制')
        validate_narration_duration(durations, target_seconds)
        if target_seconds <= 45:
            max_segments, min_seconds = 6, 4.0
        else:
            max_segments, min_seconds = 8, 4.5
        enforce_plan = target_seconds >= 30
        if enforce_plan and len(scenes) > max_segments:
            raise ValueError(f'目标时长 {target_seconds} 秒最多使用 {max_segments} 个镜头')
        if enforce_plan and any(duration < min_seconds for duration in durations):
            raise ValueError(f'每个分镜旁白至少需要 {min_seconds:.1f} 秒')
        for i, scene in enumerate(scenes):
            duration = durations[i]
            image = f'image-{i}.png'; audio = f'audio-{i}.mp3'; segment = f'segment-{i}.mp4'
            shutil.copyfile(scene.image, work / image); shutil.copyfile(scene.audio, work / audio)
            vf = f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1'
            _run([ffmpeg, '-v','error','-y','-loop','1','-framerate','24','-i',image,'-i',audio,
                  '-t',str(duration),'-vf',vf,'-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p',
                  '-c:a','aac','-ar','48000','-ac','2','-shortest',segment],work)
            names.append(segment)
        _merge_subtitles(scenes, durations, work/'captions.srt')
        (work/'list.txt').write_text(''.join(f"file '{name}'\n" for name in names),encoding='utf-8')
        _run([ffmpeg,'-v','error','-y','-f','concat','-safe','1','-i','list.txt','-c','copy','combined.mp4'],work)
        _run([ffmpeg,'-v','error','-y','-i','combined.mp4','-vf',"subtitles=captions.srt:force_style='FontName=Noto Sans CJK SC,FontSize=16,Outline=1,MarginV=36'",
              '-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','copy','final.mp4'],work)
        shutil.copyfile(work/'final.mp4',output);shutil.copyfile(work/'captions.srt',captions)
    return durations

def validate_narration_duration(durations: list[float], target_seconds: int) -> None:
    """Use measured audio duration as the final authority for target length."""
    if not durations or any(d <= 0 for d in durations):
        raise ValueError('旁白音频时长无效')
    actual = sum(durations)
    if abs(actual-target_seconds) > max(3, target_seconds * .15):
        raise ValueError(f'旁白实际时长 {actual:.1f} 秒，不符合目标 {target_seconds} 秒')


def mix_background_music(video: Path, music: Path, output: Path, *, ffmpeg: str = 'ffmpeg',
                         volume: float = 0.08) -> None:
    """Mix a caller-supplied, licensed music file under narration."""
    if not 0 <= volume <= 0.2: raise ValueError('背景音乐音量超出范围')
    if output.exists(): raise FileExistsError('输出文件已存在')
    if not video.is_file() or not music.is_file(): raise ValueError('输入媒体不存在')
    command=[ffmpeg,'-v','error','-y','-i',str(video.resolve()),'-stream_loop','-1','-i',str(music.resolve()),
             '-filter_complex',f'[1:a]volume={volume}[bg];[0:a][bg]amix=inputs=2:duration=first:normalize=0[a]',
             '-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-shortest',str(output.resolve())]
    try:
        subprocess.run(command,check=True,capture_output=True,timeout=180)
    except Exception:
        output.unlink(missing_ok=True)
        raise
