from __future__ import annotations

import mimetypes
from pathlib import PurePosixPath
from urllib.parse import quote

from .base import StorageObject, StorageProvider


class S3StorageProvider(StorageProvider):
    """S3-compatible object storage with private, expiring read URLs."""

    def __init__(self, *, bucket: str, client, prefix: str = "", public_url: str = "",
                 url_expiry_seconds: int = 900):
        if not bucket.strip():
            raise ValueError("S3 bucket is required")
        self.bucket = bucket.strip()
        self.client = client
        self.prefix = prefix.strip("/")
        self.public_url = public_url.rstrip("/")
        self.url_expiry_seconds = max(60, min(int(url_expiry_seconds), 86400))

    @staticmethod
    def _key(value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("invalid storage key")
        return path.as_posix()

    def _object_key(self, key: str) -> str:
        normalized = self._key(key)
        return f"{self.prefix}/{normalized}" if self.prefix else normalized

    def upload(self, key: str, data: bytes, *, content_type: str) -> StorageObject:
        if not isinstance(data, bytes):
            raise TypeError("storage data must be bytes")
        normalized = self._key(key)
        effective_type = content_type or mimetypes.guess_type(normalized)[0] or "application/octet-stream"
        self.client.put_object(
            Bucket=self.bucket, Key=self._object_key(normalized), Body=data,
            ContentType=effective_type,
        )
        # Persist a stable, owner-checked application URL. The API creates a
        # fresh presigned redirect only after authorizing the requesting user.
        url = "/api/storage/" + quote(normalized, safe="/")
        return StorageObject(normalized, url, len(data), effective_type)

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._object_key(key))

    def get_url(self, key: str) -> str:
        object_key = self._object_key(key)
        if self.public_url:
            return f"{self.public_url}/{quote(object_key, safe='/')}"
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=self.url_expiry_seconds,
        )

    def local_path(self, key: str):
        self._key(key)
        return None
