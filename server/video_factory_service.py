"""Server-side adapters for video factory providers and durable job output."""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

from . import accounts, image_provider, storage, workbench, workbench_research
from .storage.image_ingest import _download
from .video_factory_cover import create_cover
from .video_factory_mpt import MptRenderer
from .video_factory_plan import Category, VideoProject, make_plan
from .video_factory_scene_renderer import mix_background_music


def enabled() -> bool:
    return os.getenv("VIDEO_FACTORY_ENABLED", "0").strip().lower() in {"1", "true", "yes"}


def points() -> int:
    try:
        return max(0, int(os.getenv("VIDEO_FACTORY_POINTS", "0")))
    except ValueError:
        return 0


def work_root() -> Path:
    root = Path(os.getenv("VIDEO_FACTORY_WORK_ROOT", "output/video-factory"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _source_rows(topic: str, supplied: list[dict[str, str]] | None) -> list[dict[str, str]]:
    if supplied:
        rows = [{"url": str(item.get("url") or ""), "summary": str(item.get("summary") or "")}
                for item in supplied]
        if all(row["url"] and row["summary"] for row in rows):
            return rows[:8]
    research = workbench_research.search(topic, fetch=True, max_fetch=3)
    rows: list[dict[str, str]] = []
    for item in research.get("fetched") or []:
        url = item.get("final_url") or item.get("url")
        summary = (item.get("content") or item.get("excerpt") or "").strip()
        if url and summary:
            rows.append({"url": str(url), "summary": summary[:6000]})
    for item in research.get("sources") or []:
        url = item.get("url")
        summary = (item.get("excerpt") or item.get("title") or "").strip()
        if url and summary and all(row["url"] != url for row in rows):
            rows.append({"url": str(url), "summary": summary[:1200]})
    return rows[:8]


def build_plan(payload: dict[str, Any]) -> VideoProject:
    category = str(payload.get("category") or "")
    topic = str(payload.get("topic") or "").strip()
    duration = int(payload.get("duration") or 30)
    style = str(payload.get("visual_style") or "auto")
    sources = _source_rows(topic, payload.get("sources"))
    from . import wechat_plus_service
    return make_plan(category, topic, duration, style, sources, wechat_plus_service.generate_json)


def load_or_build_plan(payload: dict[str, Any], directory: Path) -> VideoProject:
    """Persist the first plan so retries resume the same paid work."""

    path = directory / "plan.json"
    if path.is_file():
        return VideoProject.model_validate_json(path.read_text(encoding="utf-8"))
    plan = build_plan(payload)
    directory.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)
    return plan


def generate_scene_image(scene, target: Path, idempotency_key: str) -> None:
    if target.exists():
        return
    with workbench.provider_overrides(request_idempotency_key=idempotency_key):
        result = image_provider.generate({
            "prompt": scene.visual_prompt,
            "size": "1080x1920",
            "n": 1,
        })
    data = result.get("data") if isinstance(result, dict) else None
    item = data[0] if isinstance(data, list) and data else {}
    encoded = item.get("b64_json") if isinstance(item, dict) else None
    if encoded:
        raw = base64.b64decode(encoded, validate=True)
    elif isinstance(item, dict) and item.get("url"):
        raw = _download(str(item["url"]))
    else:
        raise ValueError("图片 Provider 未返回图片数据")
    raw = image_provider.ensure_png(raw)
    if len(raw) > 24 * 1024 * 1024:
        raise ValueError("单张分镜图片超过 24MB")
    target.write_bytes(raw)


class NarrationRenderer(MptRenderer):
    def __init__(self, *args, rate: float = 1.2, **kwargs):
        super().__init__(*args, **kwargs)
        self.rate = rate

    def create_narration(self, text: str, voice_id: str, rate: float | None = None) -> str:
        return super().create_narration(text, voice_id, rate=self.rate if rate is None else rate)


def mpt_renderer() -> NarrationRenderer:
    base_url = os.getenv("VIDEO_FACTORY_MPT_BASE_URL", "").strip()
    api_key = os.getenv("VIDEO_FACTORY_MPT_API_KEY", "").strip()
    if not base_url or not api_key:
        raise RuntimeError("视频渲染服务尚未配置")
    try:
        rate = float(os.getenv("VIDEO_FACTORY_TTS_RATE", "1.2"))
    except ValueError:
        rate = 1.2
    return NarrationRenderer(base_url, api_key, rate=max(0.7, min(1.3, rate)))


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_bundle(plan: VideoProject, directory: Path, report: dict[str, Any]) -> dict[str, str]:
    """Write the user-visible bundle and optionally mix configured music."""
    scene = directory / "scene-1.png"
    cover = directory / "cover.jpg"
    if not cover.exists():
        create_cover(scene, cover, plan.cover_title)
    final = directory / "final.mp4"
    music_path = os.getenv("VIDEO_FACTORY_BGM_PATH", "").strip()
    music_video = directory / "final-with-music.mp4"
    if music_path and Path(music_path).is_file() and not music_video.exists():
        mix_background_music(final, Path(music_path), music_video)
    selected_video = music_video if music_video.is_file() else final
    _write_json(directory / "script.json", {
        "title": plan.title,
        "cover_title": plan.cover_title,
        "category": plan.category,
        "topic": plan.topic,
        "duration_target": plan.duration_target,
        "narration": [scene.narration for scene in plan.scenes],
    })
    _write_json(directory / "storyboard.json", [scene.model_dump() for scene in plan.scenes])
    _write_json(directory / "sources.json", [
        {"url": ref, "summary": "来源用于计划约束；发布前仍需逐条核验。"}
        for scene in plan.scenes for ref in scene.evidence_refs
    ])
    _write_json(directory / "cost_report.json", {
        "status": "unknown",
        "note": "供应商账单未回传时不能把估算值写成真实成本。",
        "provider_usage": {"text": "not_reported", "images": "not_reported", "tts": "not_reported"},
    })
    _write_json(directory / "quality_report.json", report)
    return {
        "video": str(selected_video),
        "cover": str(cover),
        "captions": str(directory / "captions.srt"),
        "script": str(directory / "script.json"),
        "storyboard": str(directory / "storyboard.json"),
        "sources": str(directory / "sources.json"),
        "quality": str(directory / "quality_report.json"),
        "cost": str(directory / "cost_report.json"),
    }


def upload_bundle(user_id: str, job_id: str, bundle: dict[str, str]) -> dict[str, dict[str, str]]:
    provider = storage.get_storage()
    content_types = {
        "video": "video/mp4",
        "cover": "image/jpeg",
        "captions": "application/x-subrip",
        "script": "application/json",
        "storyboard": "application/json",
        "sources": "application/json",
        "quality": "application/json",
        "cost": "application/json",
    }
    stored: dict[str, dict[str, str]] = {}
    for name, raw_path in bundle.items():
        path = Path(raw_path)
        if not path.is_file() or path.stat().st_size <= 0:
            raise ValueError(f"视频成果缺失：{name}")
        if path.stat().st_size > 200 * 1024 * 1024:
            raise ValueError(f"视频成果文件过大：{name}")
        key = f"video-factory/{user_id}/{job_id}/{path.name}"
        obj = provider.upload(key, path.read_bytes(), content_type=content_types[name])
        stored[name] = {"key": obj.key, "url": obj.url, "size": obj.size, "content_type": obj.content_type}
    return stored


def run_plan(job: dict[str, Any], progress) -> dict[str, Any]:
    payload = json.loads(job.get("payload_json") or "{}")
    directory = work_root() / job["id"]
    started = time.monotonic()
    progress("research")
    plan = load_or_build_plan(payload, directory)
    progress("image")
    from .video_factory_pipeline import run_project
    report = run_project(plan, directory, mpt_renderer(), generate_scene_image)
    progress("quality")
    from .video_factory_quality import inspect_av
    report["av_checks"] = inspect_av(directory / "final.mp4")
    bundle = build_bundle(plan, directory, report)
    progress("store")
    stored = upload_bundle(job["user_id"], job["id"], bundle)
    return {
        "video": stored["video"],
        "cover": stored["cover"],
        "scripts": {
            "cover_title": plan.cover_title,
            "narration": [scene.narration for scene in plan.scenes],
        },
        "storyboard": [scene.model_dump() for scene in plan.scenes],
        "quality_report": report,
        "assets": stored,
        "renderer": "mpt-tts+ffmpeg-scenes",
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
