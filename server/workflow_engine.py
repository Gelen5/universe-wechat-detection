"""One node engine shared by automatic and interactive creator modes."""
from __future__ import annotations

from typing import Any

from . import accounts, workbench
from . import skill_article_adapter
from .workflow_repository import NODES


def _legacy_session(workflow: dict[str, Any]) -> dict[str, Any]:
    session = accounts.load_workbench_session(workflow["id"], workflow["user_id"])
    if not session:
        raise RuntimeError("creator session checkpoint is missing")
    return session


def execute_node(workflow: dict[str, Any], node_name: str) -> dict[str, Any]:
    """Execute exactly one durable node using the existing proven creator rules."""
    data = workflow["input"]
    user_id = workflow["user_id"]
    workflow_id = workflow["id"]
    decisions = (workflow.get("state") or {}).get("decisions") or {}
    if node_name == "intent":
        article_state = skill_article_adapter.initialize(
            data.get("topic", ""), workflow["mode"], data.get("persona", "深度观察者"),
        )
        return {"intent": {"topic": data.get("topic", ""), "persona": data.get("persona", "深度观察者"),
                           "theme": data.get("theme", "default")}, "article_state": article_state}
    if node_name == "topic":
        session = workbench.create(data.get("topic", ""), "interactive", data.get("persona", "深度观察者"),
                                   data.get("theme", "default"), user_id=user_id, session_id=workflow_id)
        stored = _legacy_session(workflow)
        stored["mode"] = workflow["mode"]
        accounts.save_workbench_session(user_id, stored)
        session["mode"] = workflow["mode"]
        result = {"legacy_session_id": workflow_id, "topic_candidates": session.get("suggestions", [])}
    elif node_name == "research":
        session = _legacy_session(workflow)
        result = {"research": {"sources": session.get("research_sources", []),
                             "verification": session.get("research_verification", {}),
                             "candidate_count": len(session.get("suggestions") or [])}}
    elif node_name == "strategy":
        selection = int((decisions.get("topic") or {}).get("selection", 1))
        session = workbench.step(workflow_id, 2, selection=selection, user_id=user_id)
        result = {"selected_topic": session.get("selected_topic"), "strategy": session.get("framework")}
    elif node_name == "draft":
        session = workbench.step(workflow_id, 3, user_id=user_id)
        result = {"article": session.get("article", "")}
    elif node_name == "review":
        session = workbench.step(workflow_id, 4, user_id=user_id)
        result = {"article": session.get("article", ""), "review": session.get("review"), "score": session.get("score")}
    elif node_name == "visual":
        session = workbench.step(workflow_id, 5, user_id=user_id)
        result = {"image_plan": session.get("image_plan"), "image_policy": session.get("image_policy", "auto")}
    elif node_name == "delivery":
        visual_decision = decisions.get("visual") or {}
        if visual_decision.get("image_policy") == "none":
            session = _legacy_session(workflow)
            session["image_policy"] = "none"
            accounts.save_workbench_session(user_id, session)
        workbench.step(workflow_id, 6, user_id=user_id)
        session = workbench.step(workflow_id, 7, user_id=user_id)
        result = {"article": session.get("article", ""), "images": session.get("images", []),
                "preview_url": session.get("preview_url"), "html_download_url": session.get("html_download_url")}
    else:
        raise ValueError(f"unknown node: {node_name}")
    article_payload = (workflow.get("state") or {}).get("article_state")
    if not article_payload:
        raise RuntimeError("latest Skill ArticleState is missing")
    result["article_state"] = skill_article_adapter.apply_node(
        article_payload, node_name, result, workbench.OUTPUT_DIR / workflow_id / "article-state",
    )
    return result
