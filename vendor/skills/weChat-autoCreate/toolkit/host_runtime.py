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
MAX_ATTEMPTS = 3


def parse_result(raw: str) -> Dict[str, Any]:
    """Parse a model reply into the object the workflow expects.

    A long outline can be cut off at the token limit, which leaves valid-looking
    JSON with unclosed arrays. Rather than failing the run, trim back to the last
    complete element and close what is open.
    """
    cleaned = _FENCE.sub("", (raw or "").strip())
    try:
        data = json.loads(cleaned)
    except ValueError:
        data = json.loads(_repair_truncated(cleaned))
    if not isinstance(data, dict):
        raise ValueError("节点回答必须是 JSON 对象")
    return data


def _repair_truncated(text: str) -> str:
    """Close a JSON object that was cut off mid-array or mid-string."""
    text = text.rstrip().rstrip(',')
    # Drop a dangling key/value stub such as `"claim": "未写完` .
    cut = text.rfind('",')
    stack: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in '[{':
            stack.append(char)
        elif char in ']}' and stack:
            stack.pop()
    if in_string:
        text += '"'
    for opener in reversed(stack):
        text += ']' if opener == '[' else '}'
    del cut
    return text


def _filter_fields(record: Any, cls: Any) -> Any:
    """Drop keys the dataclass does not declare.

    Models routinely add a helpful-looking field (``verification``) to a source
    record; ``SourceRecord(**item)`` then raises and fails the whole run.
    """
    import dataclasses
    if not isinstance(record, dict) or not dataclasses.is_dataclass(cls):
        return record
    allowed = {field.name for field in dataclasses.fields(cls)}
    return {key: value for key, value in record.items() if key in allowed}


def _coerce(node: str, result: Dict[str, Any]) -> Dict[str, Any]:
    """Tolerate the shapes a model reliably gets wrong.

    ``evidence_pack.sources`` is declared as a ledger object but arrives as a
    bare array, which crashes the dataclass round-trip; ``claims`` occasionally
    arrives as a mapping, and records carry keys the dataclass does not declare.
    Normalising here keeps a malformed answer from failing a whole run.
    """
    if node == "research":
        from .article_state import ClaimRecord, SourceRecord
        pack = result.get("evidence_pack")
        if isinstance(pack, dict):
            sources = pack.get("sources")
            if isinstance(sources, list):
                pack["sources"] = {"records": sources}
            elif not isinstance(sources, dict):
                pack["sources"] = {"records": []}
            records = (pack.get("sources") or {}).get("records")
            if isinstance(records, list):
                pack["sources"]["records"] = [_filter_fields(item, SourceRecord) for item in records]
            if isinstance(pack.get("claims"), dict):
                pack["claims"] = list(pack["claims"].values())
            elif not isinstance(pack.get("claims"), list):
                pack["claims"] = []
            pack["claims"] = [_filter_fields(item, ClaimRecord) for item in pack["claims"]]
    if node == "strategy":
        outline = result.get("outline")
        if isinstance(outline, dict):
            result["outline"] = list(outline.values())
    return result


def run_node_with(state: ArticleState, node: str,
                  generate: Callable[[str], str], *,
                  root: str | Path | None = None,
                  output_dir: str | Path | None = None,
                  validate_result: Callable[[Dict[str, Any]], str] | None = None,
                  max_attempts: int | None = None) -> ArticleState:
    """Run `node` until it passes, blocking, or exhausts its attempts."""
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    feedback = ""
    for _attempt in range(max_attempts or MAX_ATTEMPTS):
        run_node(state, node, output_dir=output_dir)
        item = state.nodes[node]
        if item.status != "awaiting_host":
            return state
        prompt = render(item.request, root, node=node)
        if feedback:
            # Asking the same question twice returns the same answer; the node's
            # own complaint is what the model has to act on.
            prompt = (feedback + "\n\n" + prompt)
        reply = generate(prompt)
        try:
            result = _coerce(node, parse_result(reply))
        except ValueError as exc:
            # Drafts can be long and contain quotes/newlines. A malformed model
            # envelope must not discard a paid generation without a retry.
            feedback = (f'上一次回答不是合法 JSON：{exc}。请重新生成完整结果，'
                        '只返回一个 JSON 对象，正确转义正文中的引号和换行。'
                        '正文内容不得缩短或省略。')
            continue
        issue = validate_result(result) if validate_result else ''
        if issue:
            feedback = f'上一次大纲未通过检查：{issue}。请只修正这个问题，返回完整、简短的 JSON；每节标题不同且无占位符。'
            continue
        feedback = ''
        apply_host_result(state, node, result)
        if validate_result:
            run_node(state, node, output_dir=output_dir)
        if state.nodes[node].status in {"passed", "blocked"}:
            return state
        reason = state.nodes[node].message or "上一次回答没有通过本节点的检查"
        feedback = f"上一次的回答被本节点拒绝，原因：{reason}\n请针对这个原因修正，重新给出完整结果。"
    if validate_result and not feedback:
        run_node(state, node, output_dir=output_dir)
        if state.nodes[node].status == 'passed':
            return state
    if feedback:
        raise ValueError(f'{node} 节点未通过检查：{feedback}')
    return state
