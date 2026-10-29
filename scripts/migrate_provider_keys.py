"""Encrypt existing provider_settings secrets after setting PROVIDER_SETTINGS_FERNET_KEY."""
from __future__ import annotations

import os
import sys

from server import accounts, provider_key_crypto


def main() -> None:
    if not os.getenv("PROVIDER_SETTINGS_FERNET_KEY"):
        raise SystemExit("PROVIDER_SETTINGS_FERNET_KEY is required")
    with accounts.DB_LOCK, accounts._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT text_api_key,image_api_key FROM provider_settings WHERE id=1"
        ).fetchone()
        if not row:
            raise SystemExit("provider_settings row is missing")
        original = [provider_key_crypto.decrypt(row[name] or "") for name in ("text_api_key", "image_api_key")]
        rollback = sys.argv[1:] == ["--decrypt-for-rollback"]
        if sys.argv[1:] and not rollback:
            raise SystemExit("usage: python -m scripts.migrate_provider_keys [--decrypt-for-rollback]")
        encrypted = original if rollback else [provider_key_crypto.encrypt(value) for value in original]
        connection.execute(
            "UPDATE provider_settings SET text_api_key=?,image_api_key=? WHERE id=1", encrypted
        )
        connection.execute("COMMIT")
    current = accounts.provider_settings(include_secrets=True)
    assert all(current[name] == value for name, value in zip(("text_api_key", "image_api_key"), original))
    print("provider_settings credentials readable; storage mode=" + ("plaintext rollback" if rollback else "encrypted"))


if __name__ == "__main__":
    main()
