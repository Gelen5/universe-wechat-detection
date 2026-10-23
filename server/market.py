"""AI 超市：只读索引 + 管理员精选/手工收录。

读取全部来自本地快照（market_sync 写入），请求路径不访问 GitHub。
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import accounts, market_sync

router = APIRouter()
STATIC = Path(__file__).resolve().parents[1] / "static"

_cache: dict[str, Any] = {"snapshot_mtime": -1.0, "custom_mtime": -1.0, "items": [], "meta": {}, "custom": {}}
PAGE_SIZE_MAX = 60


# ---------------------------------------------------------------- 数据读取
def _load() -> tuple[list[dict[str, Any]], dict, dict]:
    snap = market_sync.snapshot_path()
    custom_file = market_sync.custom_path()
    snap_mtime = snap.stat().st_mtime if snap.exists() else 0.0
    custom_mtime = custom_file.stat().st_mtime if custom_file.exists() else 0.0
    if snap_mtime != _cache["snapshot_mtime"]:
        payload = market_sync.read_json(snap, {}) or {}
        _cache["items"] = payload.get("items") or []
        _cache["meta"] = {key: payload.get(key) for key in
                          ("generated_at", "source", "count", "translated") if key in payload}
        _cache["snapshot_mtime"] = snap_mtime
    if custom_mtime != _cache["custom_mtime"]:
        _cache["custom"] = market_sync.read_json(custom_file, {}) or {}
        _cache["custom_mtime"] = custom_mtime
    return _cache["items"], _cache["meta"], _cache["custom"]


def _merged() -> list[dict[str, Any]]:
    """快照 + 手工条目 - 隐藏；手工条目同 id 时覆盖快照。"""
    items, _meta, custom = _load()
    hidden = {str(x) for x in (custom.get("hidden") or [])}
    pins = {str(pin.get("id")): pin for pin in (custom.get("pins") or []) if isinstance(pin, dict)}
    manual = [dict(row, manual=True) for row in (custom.get("items") or []) if isinstance(row, dict)]
    by_id: dict[str, dict[str, Any]] = {}
    for row in manual + list(items):
        if not row.get("id"):
            continue
        by_id[str(row["id"])] = row
    merged: list[dict[str, Any]] = []
    for item_id, row in by_id.items():
        if item_id in hidden:
            continue
        pin = pins.get(item_id)
        row = dict(row)
        row["featured"] = bool(pin)
        row["pin_rank"] = int(pin["rank"]) if pin and pin.get("rank") is not None else None
        row["pin_note"] = str(pin.get("note") or "") if pin else ""
        merged.append(row)
    return merged


def _matches(row: dict[str, Any], query: str) -> bool:
    if not query:
        return True
    haystack = " ".join(str(row.get(key) or "") for key in
                        ("name", "name_zh", "description", "description_zh", "repo", "path"))
    tags = row.get("tags") or []
    haystack += " " + " ".join(str(tag) for tag in tags if isinstance(tag, str))
    return query in haystack.lower()


def _sort(items: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
    if mode == "added":
        return sorted(items, key=lambda row: (str(row.get("added_at") or ""), row.get("stars", 0)), reverse=True)
    if mode == "manual":
        pinned = sorted([row for row in items if row.get("featured")],
                        key=lambda row: (row.get("pin_rank") if row.get("pin_rank") is not None else 9999))
        pinned_ids = {row["id"] for row in pinned}
        manual = [row for row in items if row.get("manual") and row["id"] not in pinned_ids]
        rest = sorted([row for row in items if row["id"] not in pinned_ids and not row.get("manual")],
                      key=lambda row: (-int(row.get("stars") or 0), row.get("name", "")))
        return pinned + manual + rest
    return sorted(items, key=lambda row: (-int(row.get("stars") or 0), row.get("name", "")))


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in (
        "id", "name", "name_zh", "description", "description_zh", "category", "category_zh",
        "authors", "official", "tags", "repo", "path", "url", "stars", "added_at",
        "manual", "featured", "pin_rank", "pin_note")}


# ---------------------------------------------------------------- 页面
@router.get("/market", response_class=HTMLResponse, include_in_schema=False)
def page():
    html = (STATIC / "market.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- 只读 API
@router.get("/api/market/skills")
def list_skills(
    q: str = Query(default="", max_length=120),
    category: str = Query(default="", max_length=40),
    sort: str = Query(default="stars", pattern="^(stars|added|manual)$"),
    page: int = Query(default=1, ge=1, le=200),
    page_size: int = Query(default=24, ge=1, le=PAGE_SIZE_MAX),
    featured: bool = Query(default=False),
):
    items = _merged()
    query = q.strip().lower()
    if category:
        items = [row for row in items if row.get("category") == category]
    if query:
        items = [row for row in items if _matches(row, query)]
    if featured:
        rows = _sort([row for row in items if row.get("featured")], "manual")
        return {"items": [_public(row) for row in rows], "total": len(rows)}
    rows = _sort(items, sort)
    total = len(rows)
    start = (page - 1) * page_size
    return {
        "items": [_public(row) for row in rows[start:start + page_size]],
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/api/market/meta")
def market_meta():
    items, meta, _custom = _load()
    counts: dict[str, int] = {}
    manual = 0
    for row in _merged():
        counts[row.get("category") or "miscellaneous"] = counts.get(row.get("category") or "miscellaneous", 0) + 1
        if row.get("manual"):
            manual += 1
    return {
        "count": len(_merged()),
        "official": sum(1 for row in items if row.get("official")),
        "repos": len({row.get("repo") for row in items if row.get("repo")}),
        "generated_at": meta.get("generated_at"),
        "translated": meta.get("translated", 0),
        "manual": manual,
        "categories": [{"slug": slug, "name": market_sync.CATEGORIES.get(slug, "其他"),
                        "count": counts.get(slug, 0)}
                       for slug in market_sync.CATEGORIES if counts.get(slug)],
    }


# ---------------------------------------------------------------- 管理端
class ManualItem(BaseModel):
    id: str | None = Field(default=None, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=600)
    category: str = Field(default="miscellaneous", max_length=40)
    repo: str = Field(min_length=3, max_length=200)
    path: str = Field(default="", max_length=300)
    stars: int = Field(default=0, ge=0)
    url: str | None = Field(default=None, max_length=400)


class Pin(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    rank: int = Field(default=1, ge=1, le=999)
    note: str = Field(default="", max_length=120)


class PinList(BaseModel):
    pins: list[Pin] = Field(default_factory=list)


class HiddenList(BaseModel):
    hidden: list[str] = Field(default_factory=list)


def _write_custom(payload: dict) -> None:
    market_sync.write_json(market_sync.custom_path(), payload)


@router.post("/api/admin/market/sync")
def trigger_sync(request: Request):
    accounts.require_admin(request)
    try:
        from .market_sync import sync_task
        result = sync_task.apply_async(queue="text")
        return {"status": "queued", "task_id": result.id}
    except Exception as exc:  # noqa: BLE001 - broker 不可用时同步执行
        try:
            return {"status": "inline", **market_sync.sync()}
        except Exception as inner:  # noqa: BLE001
            raise HTTPException(503, f"同步失败: {inner}") from exc


@router.post("/api/admin/market/items", status_code=201)
def upsert_item(payload: ManualItem, request: Request):
    accounts.require_admin(request)
    custom = market_sync.read_json(market_sync.custom_path(), {}) or {}
    items = [row for row in (custom.get("items") or []) if isinstance(row, dict)]
    item_id = payload.id or f"manual-{uuid.uuid4().hex[:10]}"
    repo = payload.repo.strip().strip("/")
    path = payload.path.strip()
    row = {
        "id": item_id,
        "name": payload.name.strip(),
        "name_zh": payload.name.strip(),
        "description": payload.description.strip(),
        "description_zh": payload.description.strip(),
        "category": payload.category if payload.category in market_sync.CATEGORIES else "miscellaneous",
        "category_zh": market_sync.CATEGORIES.get(payload.category, "其他"),
        "authors": [repo.split("/")[0]] if "/" in repo else [],
        "official": False,
        "tags": [],
        "repo": repo,
        "path": path,
        "url": payload.url or market_sync.github_url(repo, path),
        "stars": payload.stars,
        "added_at": time.strftime("%Y-%m-%d"),
        "manual": True,
    }
    items = [row for row in items if row.get("id") != item_id] + [row]
    custom["items"] = items
    _write_custom(custom)
    return {"item": row}


@router.delete("/api/admin/market/items/{item_id}")
def delete_item(item_id: str, request: Request):
    accounts.require_admin(request)
    custom = market_sync.read_json(market_sync.custom_path(), {}) or {}
    custom["items"] = [row for row in (custom.get("items") or [])
                       if isinstance(row, dict) and row.get("id") != item_id]
    custom["pins"] = [pin for pin in (custom.get("pins") or [])
                      if isinstance(pin, dict) and pin.get("id") != item_id]
    _write_custom(custom)
    return {"status": "deleted", "id": item_id}


@router.get("/api/admin/market/custom")
def admin_custom(request: Request):
    accounts.require_admin(request)
    custom = market_sync.read_json(market_sync.custom_path(), {}) or {}
    return {"items": custom.get("items") or [], "pins": custom.get("pins") or [],
            "hidden": custom.get("hidden") or []}


@router.post("/api/admin/market/pins")
def set_pins(payload: PinList, request: Request):
    accounts.require_admin(request)
    custom = market_sync.read_json(market_sync.custom_path(), {}) or {}
    custom["pins"] = [pin.model_dump() for pin in payload.pins]
    _write_custom(custom)
    return {"pins": custom["pins"]}


@router.post("/api/admin/market/hidden")
def set_hidden(payload: HiddenList, request: Request):
    accounts.require_admin(request)
    custom = market_sync.read_json(market_sync.custom_path(), {}) or {}
    merged: list[str] = []
    for item_id in list(custom.get("hidden") or []) + [str(x) for x in payload.hidden]:
        if item_id and item_id not in merged:
            merged.append(item_id)
    custom["hidden"] = merged[:500]
    _write_custom(custom)
    return {"hidden": custom["hidden"]}


@router.delete("/api/admin/market/hidden/{item_id}")
def unhide(item_id: str, request: Request):
    accounts.require_admin(request)
    custom = market_sync.read_json(market_sync.custom_path(), {}) or {}
    custom["hidden"] = [x for x in (custom.get("hidden") or []) if str(x) != item_id]
    _write_custom(custom)
    return {"hidden": custom["hidden"]}
