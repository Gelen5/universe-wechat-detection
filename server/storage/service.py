from __future__ import annotations

import os
import threading
from pathlib import Path

from .base import StorageProvider
from .local import LocalStorageProvider
from .s3 import S3StorageProvider


_lock = threading.Lock()
_provider: StorageProvider | None = None
_signature: tuple[str, ...] | None = None


def get_storage(*, refresh: bool = False) -> StorageProvider:
    global _provider, _signature
    kind = os.getenv("STORAGE_PROVIDER", "local").strip().lower()
    root = os.getenv("LOCAL_STORAGE_ROOT", "").strip()
    signature = (
        kind, root, os.getenv("S3_ENDPOINT_URL", ""), os.getenv("S3_REGION", ""),
        os.getenv("S3_BUCKET", ""), os.getenv("S3_PREFIX", ""),
        os.getenv("S3_PUBLIC_URL", ""), os.getenv("S3_ACCESS_KEY_ID", ""),
        os.getenv("S3_SECRET_ACCESS_KEY", ""), os.getenv("S3_URL_EXPIRY_SECONDS", "900"),
    )
    with _lock:
        if refresh or _provider is None or _signature != signature:
            if kind == "local":
                effective_root = Path(root) if root else Path(__file__).resolve().parents[2] / "output" / "storage"
                _provider = LocalStorageProvider(effective_root)
            elif kind == "s3":
                import boto3

                client = boto3.client(
                    "s3", endpoint_url=os.getenv("S3_ENDPOINT_URL") or None,
                    region_name=os.getenv("S3_REGION") or None,
                    aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID") or None,
                    aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY") or None,
                )
                _provider = S3StorageProvider(
                    bucket=os.getenv("S3_BUCKET", ""), client=client,
                    prefix=os.getenv("S3_PREFIX", ""), public_url=os.getenv("S3_PUBLIC_URL", ""),
                    url_expiry_seconds=int(os.getenv("S3_URL_EXPIRY_SECONDS", "900")),
                )
            else:
                raise RuntimeError(f"unsupported STORAGE_PROVIDER: {kind}")
            _signature = signature
        return _provider
