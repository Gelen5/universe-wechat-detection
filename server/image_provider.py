"""Reusable server-side image provider call for synchronous routes and workers."""
from __future__ import annotations

import base64
import io
import math
import re
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
        requested_size = str(payload.get("size") or "1024x1365")
        body = {
            "model": workbench._setting("WECHAT_IMAGE_MODEL") or str(payload.get("model") or "gpt-image-2"),
            "prompt": str(payload.get("prompt") or ""),
            "size": _request_size(requested_size, workbench._setting("WECHAT_IMAGE_MODEL") or str(payload.get("model") or "gpt-image-2")),
            "n": int(payload.get("n") or 1),
        }
        if not body["prompt"].strip():
            raise ImageProviderError("图片提示词不能为空")
        # gpt-image-2.5 only accepts `size=auto` and composes the frame itself,
        # so a square or 3:4 request came back landscape. State the wanted ratio
        # inside the prompt, then force the exact pixel size on the way out.
        hint = _ratio_hint(requested_size)
        if hint:
            body["prompt"] = f"{body['prompt'].strip()}\n\n{hint}"
        from .providers import ModelService, OpenAICompatibleProvider, ProviderRequestError
        from .providers import call_context
        # Image work triggered from inside a tool belongs to that Run too; the
        # bare client used to drop its cost out of Run and ProviderCall totals.
        attribution = call_context.current()
        provider = OpenAICompatibleProvider(
            api_key=workbench._setting("WECHAT_TEXT_API_KEY") or api_key,
            base_url=workbench._setting("WECHAT_TEXT_API_BASE_URL") or base_url,
            text_model=workbench._setting("WECHAT_TEXT_MODEL", "gpt-4.1-mini"),
            image_api_key=api_key, image_base_url=base_url, image_model=body["model"],
            verify_ssl=workbench._verify_ssl(),
        )
        image_timeout = 300
        remaining = call_context.remaining_seconds()
        if remaining is not None:
            image_timeout = max(1, min(image_timeout, remaining))
        try:
            result = ModelService(
                provider,
                usage_recorder=attribution.get("usage_recorder"),
                cost_policy=attribution.get("cost_policy"),
            ).generate_image(
                body["prompt"], size=body["size"], count=body["n"], timeout=image_timeout,
                idempotency_key=(attribution.get("idempotency_key")
                                 or workbench._setting("WECHAT_REQUEST_IDEMPOTENCY_KEY") or None),
                run_id=attribution.get("run_id"), user_id=attribution.get("user_id"),
            )
        except ProviderRequestError as exc:
            raise ImageProviderError(f"图片接口请求失败：{exc}") from exc
        return _fit_images(result, requested_size)


# Models that reject an explicit pixel size and only accept `auto`; they pick
# the frame themselves, so the size has to be enforced after the fact.
_AUTO_ONLY_MODELS = ("gpt-image",)


def _request_size(size: str, model: str) -> str:
    """The `size` value the provider will actually accept for this model."""
    name = model.strip().lower()
    return "auto" if any(name.startswith(prefix) for prefix in _AUTO_ONLY_MODELS) else size


_SIZE_PATTERN = re.compile(r"^\s*(\d{2,5})\s*[xX*]\s*(\d{2,5})\s*$")
_STANDARD_RATIOS = ((1, 1), (3, 4), (4, 3), (2, 3), (3, 2), (9, 16), (16, 9))


def _size_pair(size: str) -> tuple[int, int] | None:
    match = _SIZE_PATTERN.match(size or "")
    if not match:
        return None
    width, height = int(match.group(1)), int(match.group(2))
    return (width, height) if width > 0 and height > 0 else None


def _ratio_label(width: int, height: int) -> str:
    ratio = width / height
    for label_width, label_height in _STANDARD_RATIOS:
        if abs(ratio - label_width / label_height) <= 0.02:
            return f"{label_width}:{label_height}"
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _ratio_hint(size: str) -> str:
    pair = _size_pair(size)
    if not pair:
        return ""
    width, height = pair
    label = _ratio_label(width, height)
    shape = "square" if width == height else ("vertical" if width < height else "horizontal")
    return (f"Composition: exact {label} {shape} aspect ratio ({width}x{height}). "
            f"Keep the subject and any text inside safe margins; do not crop or letterbox.")


def _fit_images(result: dict[str, Any], size: str) -> dict[str, Any]:
    """Force every returned image to exactly the requested pixel size.

    Models that honour `size` pass through untouched; models that only follow
    the ratio hint get scaled, and anything still off-ratio is centre-cropped
    first so cards never come back landscape when 3:4 was requested.
    """
    pair = _size_pair(size)
    items = result.get("data") if isinstance(result, dict) else None
    if not pair or not isinstance(items, list) or not items:
        return result
    try:
        from PIL import Image
    except Exception:
        return result
    target_width, target_height = pair
    target_ratio = target_width / target_height
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
            elif item.get("url"):
                response = requests.get(str(item["url"]), timeout=(10, 90))
                response.raise_for_status()
                raw = response.content
            else:
                continue
            with Image.open(io.BytesIO(raw)) as decoded:
                decoded.load()
                width, height = decoded.size
                if (width, height) == (target_width, target_height):
                    continue
                image = decoded.convert("RGB")
                if abs(width / height - target_ratio) > 0.01:
                    if width / height > target_ratio:
                        crop_width = max(1, round(height * target_ratio))
                        left = (width - crop_width) // 2
                        image = image.crop((left, 0, left + crop_width, height))
                    else:
                        crop_height = max(1, round(width / target_ratio))
                        top = (height - crop_height) // 2
                        image = image.crop((0, top, width, top + crop_height))
                image = image.resize((target_width, target_height), Image.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
            item["b64_json"] = base64.b64encode(buffer.getvalue()).decode("ascii")
            item.pop("url", None)
            item.pop("image_url", None)
            item["width"], item["height"] = target_width, target_height
        except Exception:
            # Never fail a paid generation because post-processing hiccuped.
            continue
    return result


def _image_api_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    return f"{base if base.endswith('/v1') else base + '/v1'}/images/generations"


def _request(url: str, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    idempotency_key = workbench._setting("WECHAT_REQUEST_IDEMPOTENCY_KEY")
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        response = requests.post(url, headers=headers, json=body, timeout=120)
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
