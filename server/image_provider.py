"""Reusable server-side image provider call for synchronous routes and workers."""
from __future__ import annotations

import time
from typing import Any

import requests

from . import accounts, workbench


class ImageProviderError(RuntimeError):
    pass


def generate(payload: dict[str, Any]) -> dict[str, Any]:
    """Generate an image using ContextVar-scoped server configuration."""
    stored = accounts.provider_settings(include_secrets=True)
    with workbench.provider_overrides(
        image_api_key=stored.get("image_api_key", ""),
        image_base_url=stored.get("image_base_url", ""),
        image_model=stored.get("image_model", ""),
    ):
        api_key = workbench._setting("WECHAT_IMAGE_API_KEY")
        if not api_key:
            raise ImageProviderError("服务端尚未配置图片 API Key")
        base_url = workbench._setting("WECHAT_IMAGE_API_BASE_URL") or workbench._setting("WECHAT_API_BASE_URL", "https://api.openai.com/v1")
        body = {
            "model": workbench._setting("WECHAT_IMAGE_MODEL") or str(payload.get("model") or "gpt-image-2"),
            "prompt": str(payload.get("prompt") or ""),
            "size": str(payload.get("size") or "1024x1365"),
            "n": int(payload.get("n") or 1),
        }
        if not body["prompt"].strip():
            raise ImageProviderError("图片提示词不能为空")
        return _request(_image_api_url(base_url), api_key, body)


def _image_api_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    return f"{base if base.endswith('/v1') else base + '/v1'}/images/generations"


def _request(url: str, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body, timeout=120)
    except requests.RequestException as exc:
        raise ImageProviderError(f"图片接口请求失败：{exc}") from exc
    data = _json(response)
    if response.status_code == 202 and data.get("statusUrl"):
        return _wait_for_task(data["statusUrl"], api_key)
    if not response.ok:
        raise ImageProviderError(_error(data) or f"图片接口 HTTP {response.status_code}")
    if data.get("statusUrl") and not data.get("data"):
        return _wait_for_task(data["statusUrl"], api_key)
    return data


def _wait_for_task(status_url: str, api_key: str) -> dict[str, Any]:
    deadline, last = time.time() + 180, {}
    while time.time() < deadline:
        time.sleep(3)
        try:
            response = requests.get(status_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=35)
        except requests.RequestException as exc:
            raise ImageProviderError(f"图片任务查询失败：{exc}") from exc
        data = _json(response)
        last = data
        if not response.ok:
            raise ImageProviderError(_error(data) or f"图片任务 HTTP {response.status_code}")
        status = str(data.get("status") or "").lower()
        if status in {"completed", "succeeded", "success"}:
            return data
        if status in {"failed", "cancelled", "canceled", "error"}:
            raise ImageProviderError(_error(data) or f"图片任务失败：{status}")
    raise ImageProviderError(f"图片任务等待超时，最后状态：{last.get('status') or '未知'}")


def _json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise ImageProviderError(f"图片接口返回不是 JSON：{response.text[:300]}") from exc
    if not isinstance(data, dict):
        raise ImageProviderError("图片接口返回格式无效")
    return data


def _error(data: dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "")
    return str(error or data.get("message") or "")
