"""Small configuration loader for optional WeChat publishing."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class Config:
    def __init__(self, config_path: Optional[str] = None):
        self.data: Dict[str, Any] = {}
        path = Path(config_path or "config.json")
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def get(self, key: str, default: Any = None) -> Any:
        value: Any = self.data
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    @property
    def wechat_appid(self) -> str:
        return self.get("wechat.appid") or os.getenv("WECHAT_APPID", "")

    @property
    def wechat_secret(self) -> str:
        return self.get("wechat.secret") or os.getenv("WECHAT_SECRET", "")


def get_config(config_path: Optional[str] = None) -> Config:
    return Config(config_path)
