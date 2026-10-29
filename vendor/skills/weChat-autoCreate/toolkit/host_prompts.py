"""Render one workflow node's host request into a model prompt.

The workflow decides what a node must produce (`purpose`, `output_contract`),
which state it may see (`state_fields`), which references it may read (`read`)
and which rules bind it (`rules`). This module turns exactly that into a prompt,
so every host — the CLI and the workbench — asks the model the same question.

Nothing here invents node requirements: a node that should ask for more must
change its `_host_request` call in `article_workflow.py`, not this renderer.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def _read_references(root: Path, names: list[str]) -> list[str]:
    chunks = []
    for name in names or []:
        path = (root / name)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        chunks.append(f"\n--- {name} ---\n{text}")
    return chunks


def render(request: Dict[str, Any], root: str | Path, node: str = "") -> str:
    """Build the prompt for one host request."""
    root = Path(root)
    parts = [
        "你在执行公众号创作流程中的一个节点。只完成这个节点，不要越到下一节点。",
        f"节点目标：{request.get('purpose') or ''}",
    ]
    parts.extend(_read_references(root, list(request.get("read") or [])))
    rules = [str(rule).strip() for rule in (request.get("rules") or []) if str(rule).strip()]
    if rules:
        parts.append("\n--- 本节点规则 ---\n" + "\n".join(rules))
    state_fields = request.get("state_fields")
    if state_fields:
        parts.append("\n--- 可用状态（只使用这里的可追溯事实） ---\n"
                     + json.dumps(state_fields, ensure_ascii=False, indent=1, default=str))
    contract = request.get("output_contract") or {}
    parts.append("\n--- 输出契约 ---\n"
                 + json.dumps(contract, ensure_ascii=False, indent=1, default=str)
                 + "\n只返回满足该契约的 JSON 对象，不要输出解释或 Markdown 代码块以外的内容。")
    if node == "research":
        parts.append(
            "\n--- evidence_pack 必须的形状（照此返回，sources 是对象不是数组） ---\n"
            '{"evidence_pack": {"sources": {"records": [{"source_id": "s1", "url": "", '
            '"title": "", "retrieved_at": "", "kind": "web"}]}, '
            '"claims": [{"claim_id": "c1", "text": "一条可核对的主张", "kind": "fact", '
            '"materiality": "key", "status": "verified", "source_ids": ["s1"]}], '
            '"research_status": "complete", "limitations": []}}\n'
            "没有来源支撑的主张不要写成 fact；把它降级为 inference 或放入 limitations。")
    if node == "strategy":
        parts.append(
            "\n--- 大纲输出约束 ---\n"
            "除非用户明确指定段数，写 5 至 7 节。每节只保留 section_title（具体且互不重复）"
            "和 content_plan（一句说明本节要讲什么）；writing_strategy 保留必要字段。"
            "标题必须写出真实内容，不要用开头、判断标准、样本一等泛称，"
            "不要出现{待选类型}等占位符。控制 JSON 长度，确保一次完整返回。")
    return "\n".join(parts)
