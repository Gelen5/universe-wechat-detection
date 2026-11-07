from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server import video_tts_service as service
from server.video_factory_quality import inspect_subtitles


def test_build_srt_has_valid_ordered_timestamps(tmp_path):
    text = "读书不是逃离现实。它让我们在喧闹里，仍然能听见自己的声音。"
    content = service.build_srt(text, 5.2)
    path = tmp_path / "captions.srt"
    path.write_text(content, encoding="utf-8")
    try:
        report = inspect_subtitles(path, 5.2)
    finally:
        path.unlink(missing_ok=True)
    assert report["timing_valid"] is True
    assert report["count"] >= 2


def test_split_long_caption_text_is_bounded():
    chunks = service._split_caption_text("这是一个没有标点的长句子" * 20, limit=20)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 24 for chunk in chunks)
    assert all(chunk[0] not in "，,、；;" for chunk in chunks)


def test_subtitle_api_requires_key(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service, "API_KEY", "test-key")
    client = TestClient(service.app)
    payload = {
        "video_script": "测试中文配音。",
        "voice_name": "zh-CN-XiaoxiaoNeural-Female",
        "voice_rate": 1.2,
    }
    assert client.post("/api/v1/subtitle", json=payload).status_code == 401


def test_subtitle_api_accepts_authenticated_task_and_files(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "ROOT", tmp_path)
    monkeypatch.setattr(service, "API_KEY", "test-key")
    monkeypatch.setattr(service, "_run_task", lambda *_args: None)
    client = TestClient(service.app)
    headers = {"x-api-key": "test-key"}
    response = client.post("/api/v1/subtitle", headers=headers, json={
        "video_script": "测试中文配音。",
        "voice_name": "zh-CN-XiaoxiaoNeural-Female",
        "voice_rate": 1.2,
    })
    assert response.status_code == 200
    task_id = response.json()["data"]["task_id"]
    status = client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert status.status_code == 200
    assert status.json()["data"]["state"] == 4
    (tmp_path / task_id / "audio.mp3").write_bytes(b"audio")
    (tmp_path / task_id / "subtitle.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n测试\n",
                                                     encoding="utf-8")
    service._write_status(tmp_path / task_id / "status.json", 1)
    assert client.get(f"/tasks/{task_id}/subtitle.srt", headers=headers).status_code == 200
    assert client.get(f"/tasks/{task_id}/audio.mp3", headers=headers).status_code == 200


def test_task_file_rejects_path_traversal(monkeypatch):
    monkeypatch.setattr(service, "API_KEY", "test-key")
    client = TestClient(service.app)
    assert client.get(
        "/tasks/not-a-uuid/audio.mp3", headers={"x-api-key": "test-key"}
    ).status_code == 404
