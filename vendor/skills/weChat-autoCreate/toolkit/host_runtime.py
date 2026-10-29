"""Drive one workflow node to completion with a caller-supplied model.

The workflow is host-agnostic: it emits a request and waits. This runtime closes
that loop — advance, render the request, call the model, apply the result — so a
host only has to supply `generate(prompt) -> str`.

It deliberately does not swallow anything: a blocked node raises WorkflowBlocked,
and a reply that is not valid JSON raises ValueError, because the workflow's
gates are the point of using it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Dict

from .article_state import ArticleState
from .article_workflow import WorkflowBlocked, apply_host_result, run_node
from .host_prompts import render

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
MAX_ATTEMPTS = 2


def parse_result(raw: str) -> Dict[str, Any]:
    """Parse a model reply into the object the workflow expects."""
    cleaned = _FENCE.sub("", (raw or "").strip())
    try:
        data = json.loads(cleaned)
    except ValueError as exc:
        raise ValueError(f"节点回答不是合法 JSON：{cleaned[:160]}") from exc
    if not isinstance(data, dict):
        raise ValueError("节点回答必须是 JSON 对象")
    return data


def _coerce(node: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Tolerate the two shapes a model reliably gets wrong.

    ``evidence_pack.sources`` is declared as a ledger object but arrives as a
    bare array, which crashes the dataclass round-trip; ``claims`` occasionally
    arrives as a mapping. Normalising here keeps a malformed answer from failing
    a whole run.
    """
    if node == "research":
        pack = result.get("evidence_pack")
        if isinstance(pack, dict):
            sources = pack.get("sources")
            if isinstance(sources, list):
                pack["sources"] = {"records": sources}
            elif not isinstance(sources, dict):
                pack["sources"] = {"records": []}
            if isinstance(pack.get("claims"), dict):
                pack["claims"] = list(pack["claims"].values())
            elif not isinstance(pack.get("claims"), list):
                pack["claims"] = []
    if node == "strategy":
        outline = result.get("outline")
        if isinstance(outline, dict):
            result["outline"] = list(outline.values())
    return result


def run_node_with(state: ArticleState, node: str,
                  generate: Callable[[str], str], *,
                  root: str | Path | None = None,
                  output_dir: str | Path | None = None) -> ArticleState:
    """Run `node` until it passes, blocking, or exhausts its attempts."""
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    for _attempt in range(MAX_ATTEMPTS):
        run_node(state, node, output_dir=output_dir)
        item = state.nodes[node]
        if item.status != "awaiting_host":
            return state
        prompt = render(item.request, root, node=node)
        reply = generate(prompt)
        result = _coerce(node, parse_result(reply))
        apply_host_result(state, node, result)
        if state.nodes[node].status in {"passed", "blocked"}:
            return state
    return state
