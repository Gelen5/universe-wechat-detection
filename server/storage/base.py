from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StorageObject:
    key: str
    url: str
    size: int
    content_type: str


class StorageProvider(ABC):
    @abstractmethod
    def upload(self, key: str, data: bytes, *, content_type: str) -> StorageObject:
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_url(self, key: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def local_path(self, key: str):
        """Return a readable local path or None for remote providers."""
        raise NotImplementedError
