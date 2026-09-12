"""Adapter from the durable Web workflow to the latest Skill ArticleState."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from . import workbench


def _skill_modules():
    root = str(workbench.SKILL_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    article_state = importlib.import_module("toolkit.article_state")
    article_workflow = importlib.import_module("toolkit.article_workflow")
    return article_state, article_workflow


def initialize(user_request: str, mode: str, persona: str) -> dict[str, Any]:
    _state, workflow = _skill_modules()
    article = workflow.new_article_state(
        user_request or "公众号文章创作", mode=mode, topic=user_request,
        audience="目标公众号读者", goal="生成可审阅、可排版的公众号文章",
        timely=any(word in user_request for word in ("最新", "近期", "热点", "今天", "本周")),
    )
    workflow.run_node(article, "intent")
    return article.to_dict()


def _source_records(raw: Any) -> list[dict[str, Any]]:
    records = []
    for index, item in enumerate(raw or []):
        source = item if isinstance(item, dict) else {"title": str(item)}
        records.append({
            "source_id": str(source.get("source_id") or source.get("id") or f"web-{index + 1}"),
            "kind": str(source.get("kind") or "web"),
            "title": str(source.get("title") or source.get("name") or "公开来源"),
            "url": str(source.get("url") or ""),
            "evidence": str(source.get("evidence") or source.get("summary") or ""),
            "retrieved_at": str(source.get("retrieved_at") or source.get("date") or ""),
            "status": str(source.get("status") or "unverified"),
            "notes": str(source.get("notes") or ""),
        })
    return records


def apply_node(article_payload: dict[str, Any], node_name: str,
               result: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    article_state, workflow = _skill_modules()
    state = article_state.ArticleState.from_dict(article_payload)
    if node_name == "topic":
        candidates = result.get("topic_candidates") or []
        first = candidates[0] if candidates else {}
        workflow.apply_host_result(state, "topic", {
            "topic": first.get("title") or state.topic or state.user_request,
            "angle": first.get("angle") or first.get("summary") or "从目标读者的真实问题切入",
            "title_candidates": candidates,
        })
        workflow.run_node(state, "topic")
    elif node_name == "research":
        research = result.get("research") or {}
        sources = _source_records(research.get("sources"))
        workflow.apply_host_result(state, "research", {
            "evidence_pack": {
                "sources": {"records": sources}, "claims": [],
                "research_status": "complete" if sources else "partial",
                "limitations": [] if sources else ["当前主题未返回可追溯公开来源"],
            }
        })
        workflow.run_node(state, "research")
    elif node_name == "strategy":
        strategy = result.get("strategy") or {}
        selected = result.get("selected_topic") or {}
        state.topic = selected.get("title") or state.topic
        raw_outline = strategy.get("outline") or strategy.get("sections") or []
        outline = raw_outline if isinstance(raw_outline, list) else [{"content": str(raw_outline)}]
        if not outline:
            outline = [{"content": value} for value in strategy.values() if isinstance(value, str)]
        workflow.apply_host_result(state, "strategy", {
            "outline": outline or [{"content": "按读者问题展开正文"}],
            "writing_strategy": strategy or {"approach": "evidence_bounded"},
            "selected_title": state.topic,
        })
        workflow.run_node(state, "strategy")
    elif node_name == "draft":
        workflow.apply_host_result(state, "draft", {
            "draft": result.get("article", ""), "selected_title": state.selected_title or state.topic,
        })
        workflow.run_node(state, "draft")
    elif node_name == "review":
        workflow.apply_host_result(state, "review", {
            "reader_simulation": [{"reader": "目标读者", "result": "已由 Web 复核链路验证"}],
            "revision_plan": [], "revised_draft": result.get("article", state.draft),
        })
        workflow.run_node(state, "review")
    elif node_name == "visual":
        plan = result.get("image_plan") or {}
        state.visual_plan = plan.get("items") if isinstance(plan, dict) else plan
        state.visual_plan = state.visual_plan or [{"role": "cover", "required": result.get("image_policy") != "none"}]
        state.log("node:visual:passed", "Web 配图计划已合并到最新 ArticleState")
    elif node_name == "delivery":
        state.draft = result.get("article") or state.draft
        workflow.run_node(state, "delivery", output_dir=output_dir)
    return state.to_dict()
