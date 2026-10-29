"""Install one persistent Fernet master key in the root-owned production env file."""
from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path


path = Path("/etc/universe-wechat-detection.env")
content = path.read_text()
lines = content.splitlines()
existing = [line for line in lines if line.startswith("PROVIDER_SETTINGS_FERNET_KEY=")]
if any(line.split("=", 1)[1].strip() for line in existing):
    print("Provider master key already configured")
else:
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    lines = [line for line in lines if not line.startswith("PROVIDER_SETTINGS_FERNET_KEY=")]
    lines.append(f"PROVIDER_SETTINGS_FERNET_KEY={key}")
    path.write_text("\n".join(lines) + "\n")
    os.chmod(path, 0o600)
    print("Provider master key installed; preserve this env file securely across restores")
