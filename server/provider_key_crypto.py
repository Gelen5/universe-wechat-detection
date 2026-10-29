"""Encryption for provider credentials stored in the account database."""
from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken


PREFIX = "fernet:v1:"


def _cipher() -> Fernet | None:
    key = os.getenv("PROVIDER_SETTINGS_FERNET_KEY", "").strip()
    return Fernet(key.encode()) if key else None


def encrypt(value: str) -> str:
    if not value or value.startswith(PREFIX):
        return value
    cipher = _cipher()
    if cipher is None:
        if os.getenv("APP_ENV", "").lower() in {"production", "prod"}:
            raise RuntimeError("PROVIDER_SETTINGS_FERNET_KEY is required in production")
        return value
    return PREFIX + cipher.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value
    cipher = _cipher()
    if cipher is None:
        raise RuntimeError("PROVIDER_SETTINGS_FERNET_KEY is missing")
    try:
        return cipher.decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("provider key could not be decrypted") from exc

