from pathlib import Path

import yaml


def test_video_services_inherit_database_and_redis_environment():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    for name in ("web", "worker", "video-worker", "video-tts", "beat"):
        environment = services[name]["environment"]
        assert "DATABASE_URL" in environment, name
        assert "REDIS_URL" in environment, name
    assert services["video-worker"]["environment"]["VIDEO_FACTORY_MPT_BASE_URL"] == "http://video-tts:8080"
    assert services["video-tts"]["environment"]["VIDEO_TTS_API_KEY"] == "${VIDEO_TTS_API_KEY}"
