"""爆款贴图拆解的参考图短期存放。

拆解改成「提交任务 → 轮询」之后，参考图不能跟着任务一起写进 PostgreSQL：
jobs.payload_json 是持久化的，一旦把 base64 塞进去就违背了
「参考图只存在于请求内存、不落库」的隐私约束。

所以这里把归一化后的 JPEG 放进 Redis，任务只拿到一次性 token：
- TTL 到期自动消失（默认 30 分钟，够排队 + 拆解一轮）
- 任务跑完立刻删除，成功失败都删
- token 是 32 位随机十六进制，不可枚举、不绑定用户信息

归一化参数与 creator_tools.viral_remix_analysis 内部完全一致
（长边 1600、JPEG q85），所以拆解质量不受影响，只是把这一步提前到入队之前。
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import secrets

from redis import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
KEY_PREFIX = "remix:reference:"
TTL_SECONDS = max(60, int(os.getenv("REMIX_REFERENCE_TTL_SECONDS", "1800")))
MAX_IMAGES = 8
MAX_EDGE = 1600
MAX_BYTES = 10 * 1024 * 1024
TOKEN_PATTERN = re.compile(r"[a-f0-9]{32}")
DATA_URL_PATTERN = re.compile(r"data:image/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)")


def _client() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5)


def normalize(source: str) -> str:
    """Decode → fit inside 1600px → JPEG q85. Mirrors the analysis-side normalization."""
    match = DATA_URL_PATTERN.fullmatch((source or "").strip())
    if not match:
        raise ValueError("参考图格式错误，请上传 PNG、JPG 或 WebP")
    try:
        raw = base64.b64decode(match.group(1), validate=True)
    except ValueError as exc:
        raise ValueError("图片数据无法读取") from exc
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("每张图片最大10MB")
    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as image:
            rgb = image.convert("RGB")
            rgb.thumbnail((MAX_EDGE, MAX_EDGE))
            buffer = io.BytesIO()
            rgb.save(buffer, format="JPEG", quality=85)
    except Exception as exc:  # noqa: BLE001 - 任何解码失败都应当是 422 而不是 500
        raise ValueError("图片无法解码，请换一张完整截图") from exc
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def save(images) -> str:
    """归一化 1-8 张参考图并写入 Redis，返回一次性 token。"""
    if not isinstance(images, list) or not 1 <= len(images) <= MAX_IMAGES:
        raise ValueError("请上传1到8张参考图")
    normalized = [normalize(item) for item in images]
    token = secrets.token_hex(16)
    client = _client()
    try:
        client.setex(KEY_PREFIX + token, TTL_SECONDS, json.dumps(normalized))
    finally:
        client.close()
    return token


def load(token: str) -> list[str]:
    """取出参考图；过期或凭证不合法时统一提示重新上传。"""
    if not TOKEN_PATTERN.fullmatch(str(token or "")):
        raise ValueError("参考图凭证无效，请重新上传")
    client = _client()
    try:
        raw = client.get(KEY_PREFIX + token)
    finally:
        client.close()
    expired = ValueError("参考图已过期，请重新上传后再拆解")
    if not raw:
        raise expired
    try:
        images = json.loads(raw)
    except ValueError as exc:
        raise expired from exc
    if not isinstance(images, list) or not images:
        raise expired
    return images


def drop(token: str) -> None:
    """任务结束后清理；清理失败不影响已完成的拆解。"""
    if not TOKEN_PATTERN.fullmatch(str(token or "")):
        return
    try:
        client = _client()
        try:
            client.delete(KEY_PREFIX + token)
        finally:
            client.close()
    except Exception:  # noqa: BLE001 - TTL 兜底，不让清理异常污染任务结果
        return
