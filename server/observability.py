"""Small structured logging surface shared by web and workers."""
from __future__ import annotations

import json
import logging
import time
from typing import Any


logger = logging.getLogger("universe")


def event(name: str, **fields: Any) -> None:
    payload = {"event": name, "timestamp_ms": int(time.time() * 1000)}
    payload.update({key: value for key, value in fields.items() if value is not None})
    logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
