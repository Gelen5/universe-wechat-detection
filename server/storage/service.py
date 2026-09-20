from __future__ import annotations

import os
import threading
from pathlib import Path

from .base import StorageProvider
from .local import LocalStorageProvider


_lock = threading.Lock()
_provider: StorageProvider | None = None
_signature: tuple[str, str] | None = None


def get_storage(*, refresh: bool = False) -> StorageProvider:
    global _provider, _signature
    kind = os.getenv("STORAGE_PROVIDER", "local").strip().lower()
    root = os.getenv("LOCAL_STORAGE_ROOT", "").strip()
    signature = kind, root
    with _lock:
        if refresh or _provider is None or _signature != signature:
            if kind != "local":
                raise RuntimeError(f"unsupported STORAGE_PROVIDER: {kind}")
            effective_root = Path(root) if root else Path(__file__).resolve().parents[2] / "output" / "storage"
            _provider = LocalStorageProvider(effective_root)
            _signature = signature
        return _provider
