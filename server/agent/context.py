from __future__ import annotations

from typing import Any

from .. import conversation_repository


def conversation_messages(conversation_id: str, user_id: str, *, limit: int = 40) -> list[dict[str, Any]]:
    history = conversation_repository.list_messages(conversation_id, user_id, limit=limit)
    return [{"role": item["role"], "content": item["content"]} for item in history]
