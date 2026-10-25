"""One node engine shared by automatic and interactive creator modes."""
from __future__ import annotations

import os
import time
from typing import Any

from . import accounts, workbench
from . import skill_article_adapter
from .observability import event as log_event
from .providers import call_context
from .workflow_repository import NODES


def _legacy_session(workflow: dict[str, Any]) -> dict[str, Any]:
    session = accounts.load_workbench_session(workflow["id"], workflow["user_id"])
    if not session:
        raise RuntimeError("creator session checkpoint is missing")
    return session


def _node_budget_seconds() -> float:
    """Wall-clock budget for one node, so retries cannot run away.

    Without it the workflow path had no deadline at all: a 183-second relay
    timeout could be retried three times inside a single review node.
    """
    try:
        return max(60.0, float(os.getenv("WECHAT_NODE_BUDGET_SECONDS", "540") or 540))
    except ValueError:
        return 540.0


def execute_node(workflow: dict[str, Any], node_name: str) -> dict[str, Any]:
    """Run one node, bound its retries to a deadline, and record how long it took."""
    started = time.monotonic()
    status = "ok"
    budget = _node_budget_seconds()
    try:
        with call_context.bind(user_id=workflow.get("user_id"),
                               deadline=started + budget):
            return _execute_node(workflow, node_name)
    except Exception as exc:
        status = type(exc).__name__
        raise
    finally:
        log_event(
            "workflow.node",
            workflow_id=workflow.get("id"),
            user_id=workflow.get("user_id"),
            node=node_name,
            duration_ms=int((time.monotonic() - started) * 1000),
            status=status,
        )


def _execute_node(workflow: dict[str, Any], node_name: str) -> dict[str, Any]:
    """Execute exactly one durable node using the existing proven creator rules."""
    data = workflow["input"]
    user_id = workflow["user_id"]
    workflow_id = workflow["id"]
    decisions = (workflow.get("state") or {}).get("decisions") or {}
    # ArticleState is the durable record; the session is the working copy the
    # node functions read. Copy forward what the state already knows so a
    # restart resumes instead of regenerating work that already exists.
    state_payload = (workflow.get("state") or {}).get("article_state")
    if state_payload and node_name != "intent":
        working = accounts.load_workbench_session(workflow_id, user_id)
        if working:
            restored = skill_article_adapter.hydrate_session(working, state_payload)
            # The state is authoritative for review freshness: if it says this
            # exact draft passed review, project that verdict so the review node
            # does not run again on an unchanged draft.
            verdict = skill_article_adapter.review_state(state_payload)
            if verdict["passed"] and workbench.skill_runtime.digest(working.get("article") or "") == verdict["article_sha256"]:
                if (working.get("review") or {}).get("article_sha256") != verdict["article_sha256"]:
                    working["review"] = {"gate": "passed",
                                         "article_sha256": verdict["article_sha256"],
                                         "source": "article_state"}
                    restored["restored"].append("review")
            if restored["restored"]:
                accounts.save_workbench_session(user_id, working)
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
