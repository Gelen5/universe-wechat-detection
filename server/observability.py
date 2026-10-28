"""Small structured logging surface shared by web and workers.

The logger configures itself instead of relying on the host: uvicorn only wires
its own loggers, so under the web container every ``event()`` call was dropped
and the one signal an operator needs during an outage never reached the log.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

LOG_LEVEL = (os.getenv("LOG_LEVEL") or "INFO").upper()


def _configure(logger: logging.Logger) -> logging.Logger:
    """Attach one stdout handler, once, without duplicating Celery's output."""
    if getattr(logger, "_universe_configured", False):
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
    # Our own handler decides the format; propagating would print every event
    # twice wherever the host also configured the root logger (Celery).
    logger.propagate = False
    logger._universe_configured = True
    return logger


logger = _configure(logging.getLogger("universe"))


def event(name: str, **fields: Any) -> None:
    payload = {"event": name, "timestamp_ms": int(time.time() * 1000)}
    payload.update({key: value for key, value in fields.items() if value is not None})
    logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))
