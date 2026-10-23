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
    editable = [latest[key] for key in ("article", "outline", "markdown", "html", "report", "topic") if key in latest]
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


# Each stage only needs the work it consumes, not a 60k dump of every artifact.
# The stage tools read the authoritative version from the database themselves,
# so the model only needs enough context to pick arguments and wording.
STAGE_ARTIFACTS = {
    "topic": (),
    "outline": ("topic",),
    "writing": ("outline",),
    "deai": ("article",),
    "typeset": ("article",),
}
STAGE_BUDGET = {"topic": 0, "outline": 4000, "writing": 6000, "deai": 2000, "typeset": 2000}


def _clip(value, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit] + " …"


def stage_messages(conversation_id: str, user_id: str, *, stage: str | None,
                   limit: int = 12) -> list[dict[str, Any]]:
    """History trimmed to what this stage actually needs.

    Long conversations used to send the last 40 messages plus up to 60k chars of
    every artifact, which pushed small models over their context limit (the
    "写作" stage failed with a provider error). Per-stage budgets keep the prompt
    small and the cost predictable.
    """
    history = conversation_repository.list_messages(conversation_id, user_id, limit=200)
    tail = [item for item in history if item.get("role") in {"user", "assistant"}][-limit:]
    messages = [{"role": item["role"], "content": _clip(item.get("content"), 800)} for item in tail]

    artifacts = conversation_repository.list_artifacts(conversation_id, user_id)
    latest: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        current = latest.get(artifact["type"])
        if current is None or artifact["version"] > current["version"]:
            latest[artifact["type"]] = artifact

    sections: list[str] = []
    budget = STAGE_BUDGET.get(stage or "", 0)
    for artifact_type in STAGE_ARTIFACTS.get(stage or "", ()):
        item = latest.get(artifact_type)
        if not item or budget <= 0:
            continue
        content = _clip(item.get("content"), budget)
        budget -= len(content)
        sections.append(f"[{artifact_type} V{item['version']}]\n{content}")

    index = ", ".join(f"{name} V{item['version']}" for name, item in sorted(latest.items()))
    system = ("当前作品：" + (index or "无") +
              "。只使用下面这些与当前阶段相关的作品，不要引用或改写其它阶段的内容。")
    if sections:
        system += "\n\n" + "\n\n".join(sections)
    return [{"role": "system", "content": system}, *messages]

