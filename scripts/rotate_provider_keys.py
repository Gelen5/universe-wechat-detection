"""Validate and install replacement provider keys from stdin without logging them.

Input is one JSON object with text_key and image_key. This script is intended
for an interactive, non-echoing stdin stream; never pass keys as CLI arguments.
"""
from __future__ import annotations

import json
import sys

import requests

from server import accounts
from server.provider_key_crypto import PREFIX


def main() -> None:
    payload = json.load(sys.stdin)
    new_keys = {kind: str(payload[kind + "_key"]).strip() for kind in ("text", "image")}
    if not all(new_keys.values()):
        raise SystemExit("Both replacement keys are required")
    settings = accounts.provider_settings()
    for kind, key in new_keys.items():
        base = settings[kind + "_base_url"].rstrip("/")
        url = (base if base.endswith("/v1") else base + "/v1") + "/models"
        try:
            response = requests.get(url, headers={"Authorization": "Bearer " + key}, timeout=20)
        except requests.RequestException as exc:
            raise SystemExit(f"{kind} provider authentication check unavailable") from exc
        if response.status_code != 200:
            raise SystemExit(f"{kind} provider authentication rejected: HTTP {response.status_code}")
    with accounts.DB_LOCK, accounts._connect() as connection:
        owner = connection.execute("SELECT id FROM users WHERE email=?", (accounts.OWNER_EMAIL,)).fetchone()
        if not owner:
            raise SystemExit("Owner account missing")
        operator_id = owner["id"]
    accounts.update_provider_settings(operator_id, {
        "text_api_key": new_keys["text"], "image_api_key": new_keys["image"],
        **{name: settings[name] for name in ("text_base_url", "image_base_url", "text_model", "image_model")},
    })
    with accounts.DB_LOCK, accounts._connect() as connection:
        row = connection.execute(
            "SELECT text_api_key,image_api_key FROM provider_settings WHERE id=1"
        ).fetchone()
    if not all(str(row[kind + "_api_key"]).startswith(PREFIX) for kind in ("text", "image")):
        raise SystemExit("Provider key encryption check failed")
    current = accounts.provider_settings(include_secrets=True)
    if not all(current[kind + "_api_key"] == new_keys[kind] for kind in ("text", "image")):
        raise SystemExit("Provider key readback check failed")
    print("Replacement text and image credentials validated, encrypted, and installed")


if __name__ == "__main__":
    main()
