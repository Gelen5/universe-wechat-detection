from __future__ import annotations

from typing import Any

from .. import conversation_repository


def conversation_messages(conversation_id: str, user_id: str, *, limit: int = 40) -> list[dict[str, Any]]:
    history = conversation_repository.list_messages(conversation_id, user_id, limit=limit)
    messages = [{"role": item["role"], "content": item["content"]} for item in history]
    artifacts = conversation_repository.list_artifacts(conversation_id, user_id)
    latest: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        current = latest.get(artifact["type"])
        if current is None or artifact["version"] > current["version"]:
            latest[artifact["type"]] = artifact
    editable = [latest[key] for key in ("article", "markdown", "html", "report", "topic") if key in latest]
    if editable:
        sections = []
        budget = 60000
        for artifact in editable:
            content = str(artifact.get("content") or "")[:budget]
            budget -= len(content)
            sections.append(
                f"[Artifact {artifact['type']} V{artifact['version']} id={artifact['id']}]\n{content}"
            )
            if budget <= 0:
                break
        messages.insert(0, {
            "role": "system",
            "content": "以下是当前对话中最新的作品版本。用户要求修改、配图或排版时，必须基于这些作品，不要另起无关内容。\n\n"
                       + "\n\n".join(sections),
        })
    return messages
