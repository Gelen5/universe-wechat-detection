from __future__ import annotations

import mimetypes
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .base import StorageObject, StorageProvider


class LocalStorageProvider(StorageProvider):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(value: str) -> str:
        path = PurePosixPath(value.replace("\\", "/"))
        if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("invalid storage key")
        return path.as_posix()

    def _path(self, key: str) -> Path:
        normalized = self._key(key)
        path = (self.root / Path(*PurePosixPath(normalized).parts)).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("storage key escapes root")
        return path

    def upload(self, key: str, data: bytes, *, content_type: str) -> StorageObject:
        if not isinstance(data, bytes):
            raise TypeError("storage data must be bytes")
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(path)
        effective_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return StorageObject(self._key(key), self.get_url(key), len(data), effective_type)

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def get_url(self, key: str) -> str:
        return "/api/storage/" + quote(self._key(key), safe="/")

    def local_path(self, key: str) -> Path:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path
