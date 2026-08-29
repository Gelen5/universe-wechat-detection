"""Minimal WeChat API surface used only by TieTuPublisher."""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict, List, Optional

import requests

from .config import Config, get_config


class WeChatAPI:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self._token = ""

    def get_access_token(self) -> str:
        if self._token:
            return self._token
        if not self.config.wechat_appid or not self.config.wechat_secret:
            raise RuntimeError("缺少 WECHAT_APPID 或 WECHAT_SECRET；策划和预览不需要这些配置")
        response = requests.get(
            "https://api.weixin.qq.com/cgi-bin/token",
            params={"grant_type": "client_credential", "appid": self.config.wechat_appid, "secret": self.config.wechat_secret},
            timeout=15,
        )
        data = response.json()
        if data.get("errcode"):
            raise RuntimeError(f"获取微信 access_token 失败: {data.get('errmsg')} ({data.get('errcode')})")
        self._token = data["access_token"]
        return self._token

    def upload_image(self, file_path: str) -> Optional[str]:
        token = self.get_access_token()
        with open(file_path, "rb") as handle:
            response = requests.post(
                "https://api.weixin.qq.com/cgi-bin/media/uploadimg",
                params={"access_token": token},
                files={"media": (os.path.basename(file_path), handle)},
                timeout=30,
            )
        data = response.json()
        if data.get("errcode"):
            raise RuntimeError(f"上传正文图片失败: {data.get('errmsg')} ({data.get('errcode')})")
        return data.get("url")

    def upload_cover(self, cover_path: str) -> Optional[str]:
        token = self.get_access_token()
        with open(cover_path, "rb") as handle:
            response = requests.post(
                "https://api.weixin.qq.com/cgi-bin/material/add_material",
                params={"access_token": token, "type": "thumb"},
                files={"media": (os.path.basename(cover_path), handle)},
                timeout=30,
            )
        data = response.json()
        if data.get("errcode"):
            raise RuntimeError(f"上传封面失败: {data.get('errmsg')} ({data.get('errcode')})")
        return data.get("media_id")

    def add_draft_multi(self, articles: List[Dict[str, Any]]) -> Optional[str]:
        token = self.get_access_token()
        response = requests.post(
            "https://api.weixin.qq.com/cgi-bin/draft/add",
            params={"access_token": token}, json={"articles": articles}, timeout=30,
        )
        data = response.json()
        if data.get("errcode"):
            raise RuntimeError(f"创建贴图号草稿失败: {data.get('errmsg')} ({data.get('errcode')})")
        return data.get("media_id")
