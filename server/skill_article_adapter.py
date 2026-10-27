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


def hydrate_session(session: dict[str, Any], article_payload: dict[str, Any]) -> dict[str, Any]:
    """Project the durable ArticleState back into the working session.

    The state is the record that survives restarts; the session is the working
    copy the legacy node functions read. When the session lost a field the state
    still has (restart, failed save, older version), copy it forward so the node
    guards see it as already done instead of regenerating work that exists.
    """
    article_state, _workflow = _skill_modules()
    state = article_state.ArticleState.from_dict(article_payload)
    restored: list[str] = []

    if not str(session.get("article") or "").strip() and str(state.draft or "").strip():
        session["article"] = state.draft
        restored.append("article")

    if session.get("framework") is None and state.outline:
        lines = [
            str(item.get("content") if isinstance(item, dict) else item).strip()
            for item in state.outline
        ]
        lines = [line for line in lines if line]
        if lines:
            strategy = state.writing_strategy if isinstance(state.writing_strategy, dict) else {}
            session["framework"] = {
                "name": str(strategy.get("name") or "按材料组织"),
                "reason": "来自 ArticleState",
                "outline": lines,
                "source": "article_state",
                "writing_strategy": strategy.get("writing_strategy") or strategy,
            }
            restored.append("framework")

    title = str(state.selected_title or state.topic or "").strip()
    if not str(session.get("topic") or "").strip() and title:
        session["topic"] = title
        restored.append("topic")

    if restored:
        session.setdefault("status", "ready_for_review")
    return {"restored": restored}


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


def review_state(article_payload: dict[str, Any]) -> dict[str, Any]:
    """Whether the ArticleState considers the current draft reviewed.

    The state records which draft the review node actually passed; the session
    only remembers that *a* review happened. Deciding freshness from the state
    stops a stale session value from skipping a review a newer draft needs.
    """
    article_state, _workflow = _skill_modules()
    state = article_state.ArticleState.from_dict(article_payload)
    current_hash = workbench.skill_runtime.digest(state.draft or "")
    platform = (state.quality_report or {}).get('platform_review') or {}
    fidelity = (state.quality_report or {}).get('fidelity_gate') or {}
    editorial = (state.quality_report or {}).get('editorial_quality') or {}
    reviewed_hash = platform.get('article_sha256')
    return {
        "passed": (state.nodes["review"].status == "passed"
                   and platform.get('gate') == 'passed'
                   and fidelity.get('status') == 'passed'
                   and editorial.get('outcome') != 'structure_needs_review'
                   and bool(reviewed_hash) and reviewed_hash == current_hash),
        "article_sha256": reviewed_hash,
        "current_article_sha256": current_hash,
        "gate": platform.get('gate', 'unknown'),
    }


def _revision_plan_from(review: Any) -> list[dict[str, Any]]:
    """Turn the platform's real review rounds into the Skill's revision shape."""
    plan: list[dict[str, Any]] = []
    for record in (review or {}).get("rounds") or []:
        diagnosis = record.get("diagnosis") or {}
        for issue in diagnosis.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            plan.append({
                "source": "web_review",
                "round": record.get("round"),
                "quote": str(issue.get("quote") or ""),
                "reason": str(issue.get("reason") or ""),
                "fix": str(issue.get("fix") or ""),
            })
    return plan


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
        # Run the node first so the Skill's real hard gate (check_content with
        # strict=True) actually evaluates the draft. The previous version
        # pre-filled a fabricated reader_simulation so the node always reported
        # "passed": the state then claimed a reader simulation that never ran.
        workflow.apply_host_result(state, "review", {
            "revision_plan": _revision_plan_from(result.get("review")),
            "revised_draft": result.get("article") or state.draft,
            # This host path did not run a new reader simulation. Never carry
            # a previous review's reader verdict into a new draft or run.
            "reader_simulation": [],
        })
        review = result.get('review') or {}
        article_hash = workbench.skill_runtime.digest(state.draft or '')
        incoming_fidelity = review.get('fidelity_gate') or {}
        incoming_editorial = review.get('editorial_quality') or {}
        valid = (review.get('gate') == 'passed'
                 and incoming_fidelity.get('status') == 'passed'
                 and incoming_editorial.get('outcome') != 'structure_needs_review'
                 and review.get('article_sha256') == article_hash)
        if valid:
            workflow.run_node(state, "review")
        else:
            state.quality_report = {'hard_gate': {'status': 'not_run'}}
        node = state.nodes["review"]
        hard_passed = valid and not (state.quality_report.get('hard_gate') or {}).get('blocked', True)
        state.quality_report['platform_review'] = {'gate': review.get('gate', 'unknown'),
                                                   'article_sha256': review.get('article_sha256')}
        state.quality_report['fidelity_gate'] = review.get('fidelity_gate') or {
            'status': 'passed' if valid else 'needs_review', 'scope': 'deterministic_checks_only'}
        state.quality_report['editorial_quality'] = review.get('editorial_quality') or {
            'status': 'needs_review' if review.get('pending_review_notes') else 'not_assessed'}
        state.quality_report['human_review_status'] = 'not_performed'
        state.quality_report['reader_simulation_status'] = 'performed' if state.reader_simulation else 'skipped'
        if not valid or not hard_passed:
            node.status = 'needs_review'
            node.message = '平台复核未通过、正文版本不匹配或硬门禁未通过，需人工处理'
        elif node.status == 'awaiting_host':
            node.status = 'passed'
            node.message = '确定性检查通过；读者模拟和人工复核未执行，文章质量尚待判断'
        state.log('node:review:status', node.message)
        result["quality_report"] = state.quality_report
    elif node_name == "visual":
        plan = result.get("image_plan") or {}
        state.visual_plan = plan.get("items") if isinstance(plan, dict) else plan
        state.visual_plan = state.visual_plan or [{"role": "cover", "required": result.get("image_policy") != "none"}]
        state.log("node:visual:passed", "Web 配图计划已合并到最新 ArticleState")
    elif node_name == "delivery":
        state.draft = result.get("article") or state.draft
        workflow.run_node(state, "delivery", output_dir=output_dir)
    return state.to_dict()
