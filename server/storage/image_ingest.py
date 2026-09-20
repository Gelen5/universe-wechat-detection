from __future__ import annotations

import base64
import binascii
import io
import ipaddress
import socket
from urllib.parse import urlparse

import requests
from PIL import Image

from .base import StorageObject
from .service import get_storage


MAX_IMAGE_BYTES = 20 * 1024 * 1024


def _validate_public_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("generated image URL must be public HTTPS")
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("generated image URL resolves to a non-public address")


def _download(url: str) -> bytes:
    _validate_public_https(url)
    session = requests.Session()
    session.trust_env = False
    with session.get(url, timeout=(10, 120), stream=True, allow_redirects=False) as response:
        response.raise_for_status()
        declared = int(response.headers.get("content-length") or 0)
        if declared > MAX_IMAGE_BYTES:
            raise ValueError("generated image exceeds storage limit")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                raise ValueError("generated image exceeds storage limit")
            chunks.append(chunk)
    return b"".join(chunks)


def _decode(item: dict) -> bytes:
    encoded = item.get("b64_json")
    if encoded:
        try:
            data = base64.b64decode(str(encoded), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("generated image contains invalid base64") from exc
        if len(data) > MAX_IMAGE_BYTES:
            raise ValueError("generated image exceeds storage limit")
        return data
    url = str(item.get("url") or item.get("image_url") or "").strip()
    if url:
        return _download(url)
    raise ValueError("generated image has no supported payload")


def ingest_generated_image(item: dict, key_prefix: str) -> StorageObject:
    data = _decode(item)
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
            image_format = (image.format or "").upper()
    except Exception as exc:
        raise ValueError("generated image payload is not a valid image") from exc
    formats = {
        "PNG": ("png", "image/png"), "JPEG": ("jpg", "image/jpeg"),
        "WEBP": ("webp", "image/webp"), "GIF": ("gif", "image/gif"),
    }
    if image_format not in formats:
        raise ValueError(f"unsupported generated image format: {image_format or 'unknown'}")
    extension, content_type = formats[image_format]
    return get_storage().upload(f"{key_prefix}.{extension}", data, content_type=content_type)
