"""Technical video checks only; semantic correctness is never auto-approved."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path


def inspect_video(path: Path, target_seconds: int, ffprobe: str = 'ffprobe') -> dict:
    result = subprocess.run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            check=True, capture_output=True, text=True, timeout=30)
    info = json.loads(result.stdout)
    streams = info.get('streams', [])
    video = next((stream for stream in streams if stream.get('codec_type') == 'video'), {})
    audio = next((stream for stream in streams if stream.get('codec_type') == 'audio'), {})
    duration = float(info.get('format', {}).get('duration') or 0)
    checks = {'resolution': (video.get('width'), video.get('height')) == (1080, 1920),
              'audio_present': bool(audio), 'duration': abs(duration - target_seconds) <= max(3, target_seconds * .15),
              'size': path.stat().st_size > 10_000}
    return {'technical_checks': checks, 'duration_seconds': duration,
            'metadata_checks_pass': all(checks.values()), 'content_review': 'needs_review',
            'limitations': ['字幕边界、语音同步、事实、画面匹配与素材授权尚未自动验证']}


def inspect_subtitles(path: Path, duration_seconds: float) -> dict:
    """Check SRT timestamp ordering, not whether captions match the speech."""
    import re
    timestamp = re.compile(r'(\d{2}):(\d{2}):(\d{2}),(\d{3})\s+-->\s+(\d{2}):(\d{2}):(\d{2}),(\d{3})')
    def seconds(parts):
        h, m, s, ms = map(int, parts)
        if m >= 60 or s >= 60:
            raise ValueError('Invalid subtitle timestamp')
        return h * 3600 + m * 60 + s + ms / 1000
    try:
        blocks = re.split(r'\n\s*\n', path.read_text(encoding='utf-8-sig').strip())
        previous = 0.0
        for block in blocks:
            lines = block.splitlines()
            if len(lines) < 3 or not lines[0].strip().isdigit() or not any(x.strip() for x in lines[2:]):
                raise ValueError('Invalid subtitle entry')
            match = timestamp.fullmatch(lines[1].strip())
            if not match: raise ValueError('Invalid subtitle timing')
            start, end = seconds(match.groups()[:4]), seconds(match.groups()[4:])
            if start < previous or end <= start or end > duration_seconds + 0.25:
                raise ValueError('Subtitle timing outside video')
            previous = end
        if not blocks or not blocks[0]: raise ValueError('No subtitles')
        return {'timing_valid': True, 'count': len(blocks), 'speech_alignment': 'not_verified'}
    except (OSError, UnicodeError, ValueError):
        return {'timing_valid': False, 'count': 0, 'speech_alignment': 'not_verified'}


def inspect_av(path: Path, ffmpeg: str = 'ffmpeg') -> dict:
    """Detect long black or silent intervals; semantic quality still needs review."""
    import re
    command=[ffmpeg,'-hide_banner','-nostats','-i',str(path),'-vf','blackdetect=d=2:pix_th=0.10',
             '-af','silencedetect=noise=-45dB:d=2','-f','null','-']
    result=subprocess.run(command,capture_output=True,text=True,timeout=180)
    log=result.stderr or ''
    black=[{'start':float(a),'end':float(b),'duration':float(c)} for a,b,c in
           re.findall(r'black_start:([\d.]+)\s+black_end:([\d.]+)\s+black_duration:([\d.]+)',log)]
    silence=[{'start':float(a),'end':float(b),'duration':float(c)} for a,b,c in
             re.findall(r'silence_start:\s*([\d.]+).*?silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)',log,re.S)]
    return {'decode_ok':result.returncode==0,'black_intervals':black,'silent_intervals':silence,
            'content_review':'needs_review'}
