"""Small MPT-compatible narration service backed by Edge TTS.

Only the endpoints used by ``MptRenderer`` are implemented. The main app
continues to own images, timing, subtitles burn-in and final MP4 assembly, so
this process stays small enough for the existing single-host deployment.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

import edge_tts
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


ROOT = Path(os.getenv("VIDEO_TTS_ROOT", "output/video-tts"))
API_KEY = os.getenv("VIDEO_TTS_API_KEY", "").strip()
MAX_CONCURRENT = max(1, int(os.getenv("VIDEO_TTS_MAX_CONCURRENT", "2")))
_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT)
app = FastAPI(title="Video narration service", docs_url=None, redoc_url=None)


class SubtitleRequest(BaseModel):
    video_script: str = Field(min_length=1, max_length=1200)
    voice_name: str = Field(min_length=1, max_length=100)
    voice_rate: float = Field(default=1.0, ge=0.7, le=1.3)
    subtitle_enabled: bool = True
    bgm_type: str = "none"


def _require_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    if not API_KEY or x_api_key != API_KEY:
        raise HTTPException(401, "invalid API key")


def _task_paths(task_id: str) -> tuple[Path, Path, Path, Path]:
    try:
        normalized = str(uuid.UUID(task_id))
    except ValueError as exc:
        raise HTTPException(404, "task not found") from exc
    directory = ROOT / normalized
    return directory, directory / "audio.mp3", directory / "subtitle.srt", directory / "status.json"


def _write_status(path: Path, state: int, error: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    payload = {"state": state}
    if error:
        payload["error"] = error[-500:]
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(path)


def _timestamp(milliseconds: int) -> str:
    hours, milliseconds = divmod(max(0, milliseconds), 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _split_caption_text(text: str, limit: int = 20) -> list[str]:
    text = re.sub(r"\s+", "", text)
    chunks: list[str] = []
    for sentence in re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text):
        while len(sentence) > limit:
            cut = max(
                sentence.rfind(mark, 0, limit + 1)
                for mark in ("，", ",", "、", " ")
            )
            if cut < max(4, limit // 2):
                cut = limit
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            chunks.append(sentence)
    cleaned: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if cleaned and chunk[0] in "，,、；;":
            cleaned[-1] += chunk[0]
            chunk = chunk[1:].strip()
        if chunk:
            cleaned.append(chunk)
    return cleaned or [text]


def build_srt(text: str, duration_seconds: float) -> str:
    if not 0 < duration_seconds <= 65:
        raise ValueError("invalid narration duration")
    chunks = _split_caption_text(text)
    weights = [max(1, len(chunk)) for chunk in chunks]
    total = sum(weights)
    cursor = 0
    lines: list[str] = []
    for index, (chunk, weight) in enumerate(zip(chunks, weights), 1):
        end = cursor + max(250, round(duration_seconds * 1000 * weight / total))
        if index == len(chunks):
            end = round(duration_seconds * 1000)
        end = min(end, round(duration_seconds * 1000))
        if end <= cursor:
            end = cursor + 1
        lines.append(
            f"{index}\n{_timestamp(cursor)} --> {_timestamp(end)}\n{chunk}\n"
        )
        cursor = end
    return "\n".join(lines)


def _audio_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    duration = float(result.stdout.decode().strip())
    if not 0 < duration <= 65:
        raise ValueError("narration duration is outside the supported range")
    return duration


def _normalize_voice(value: str) -> str:
    voice = value.strip()
    return re.sub(r"-(Female|Male)$", "", voice, flags=re.I)


async def _synthesize(text: str, voice: str, rate: float, audio: Path) -> None:
    percentage = round((rate - 1.0) * 100)
    rate_value = f"{percentage:+d}%"
    communicate = edge_tts.Communicate(text, _normalize_voice(voice), rate=rate_value)
    temporary = audio.with_name(audio.name + ".part")
    size = 0
    try:
        with temporary.open("wb") as output:
            async for chunk in communicate.stream():
                if chunk["type"] != "audio":
                    continue
                data = chunk["data"]
                size += len(data)
                if size > 20 * 1024 * 1024:
                    raise ValueError("narration audio exceeds 20MB")
                output.write(data)
        if not size:
            raise RuntimeError("Edge TTS returned no audio")
        temporary.replace(audio)
    finally:
        temporary.unlink(missing_ok=True)


def _run_task(task_id: str, payload: SubtitleRequest) -> None:
    directory, audio, subtitles, status = _task_paths(task_id)
    directory.mkdir(parents=True, exist_ok=True)
    _write_status(status, 4)
    with _semaphore:
        try:
            asyncio.run(_synthesize(payload.video_script, payload.voice_name,
                                    payload.voice_rate, audio))
            duration = _audio_duration(audio)
            subtitles.write_text(
                build_srt(payload.video_script, duration), encoding="utf-8"
            )
            _write_status(status, 1)
        except Exception as exc:  # noqa: BLE001 - persisted task error
            _write_status(status, -1, str(exc) or type(exc).__name__)


@app.post("/api/v1/subtitle")
def create_subtitle(payload: SubtitleRequest, request: Request,
                    x_api_key: str | None = Header(default=None)):
    _require_key(request, x_api_key)
    task_id = str(uuid.uuid4())
    directory, _, _, status = _task_paths(task_id)
    directory.mkdir(parents=True, exist_ok=False)
    _write_status(status, 4)
    threading.Thread(
        target=_run_task,
        args=(task_id, payload),
        name=f"video-tts-{task_id[:8]}",
        daemon=True,
    ).start()
    return {"status": 200, "data": {"task_id": task_id}}


@app.get("/api/v1/tasks/{task_id}")
def task_status(task_id: str, request: Request,
                x_api_key: str | None = Header(default=None)):
    _require_key(request, x_api_key)
    _, _, _, status_path = _task_paths(task_id)
    if not status_path.is_file():
        raise HTTPException(404, "task not found")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    data = {"state": int(status["state"]), "progress": 100 if status["state"] == 1 else 0}
    if status["state"] == 1:
        data["subtitle_path"] = f"/tasks/{task_id}/subtitle.srt"
        data["audio_file"] = f"/tasks/{task_id}/audio.mp3"
    elif status.get("error"):
        data["error"] = status["error"]
    return {"status": 200, "data": data}


@app.get("/tasks/{task_id}/{filename}")
def task_file(task_id: str, filename: str, request: Request,
              x_api_key: str | None = Header(default=None)):
    _require_key(request, x_api_key)
    _, audio, subtitles, status = _task_paths(task_id)
    if not status.is_file() or json.loads(status.read_text(encoding="utf-8")).get("state") != 1:
        raise HTTPException(404, "task output not ready")
    files = {
        "audio.mp3": (audio, "audio/mpeg"),
        "subtitle.srt": (subtitles, "application/x-subrip"),
    }
    if filename not in files or not files[filename][0].is_file():
        raise HTTPException(404, "file not found")
    path, content_type = files[filename]
    return FileResponse(path, media_type=content_type,
                        headers={"Cache-Control": "private, no-store"})


@app.get("/health")
def health():
    return {"status": "ok", "edge_tts": edge_tts.__version__}
