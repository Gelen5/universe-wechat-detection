"""热点广场：聚合 newsnow 的多平台热榜，读缓存出页面。

设计约束（沿用 AI 超市那套）：
- 只读缓存：页面永远不直连上游，同步交给 Celery beat；
- 上游是第三方公共实例，必须有降级：缓存 → PG 快照 → 自有直连源；
- 只存标题/链接/热度，不存正文；
- 每小时落一份 PG 快照，为将来的排名轨迹/跨平台频次留数据。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests
from fastapi import APIRouter, Query
from redis import Redis
from sqlalchemy import delete, select

from . import database
from .models import HotspotSnapshot

logger = logging.getLogger(__name__)

router = APIRouter()

PLATFORMS = (
    ("weibo", "微博"),
    ("zhihu", "知乎"),
    ("douyin", "抖音"),
    ("toutiao", "今日头条"),
    ("baidu", "百度"),
    ("bilibili", "B站"),
    ("juejin", "掘金"),
    ("tieba", "贴吧"),
    ("douban", "豆瓣"),
    ("v2ex", "V2EX"),
    ("hackernews", "Hacker News"),
    ("github", "GitHub Trending"),
)
DEFAULT_PLATFORMS = ("weibo", "zhihu", "douyin", "toutiao", "baidu", "bilibili",
                    "juejin", "tieba", "douban", "v2ex", "hackernews", "github")
NAMES = dict(PLATFORMS)

API_URL = os.getenv("HOTSPOT_API_URL", "https://newsnow.busiyi.world/api/s")
CACHE_TTL = max(60, int(os.getenv("HOTSPOT_TTL", "900")))
RETENTION_DAYS = max(1, int(os.getenv("HOTSPOT_RETENTION_DAYS", "30")))
FETCH_TIMEOUT = (5, 12)

KEY_ITEMS = "hotspot:v1:items:{platform}"
KEY_META = "hotspot:v1:meta"
KEY_HOUR = "hotspot:v1:snapshot:hour"
KEY_LOCK = "hotspot:v1:sync:lock"

_LAST_ATTEMPT = 0.0

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"),
    "Accept": "application/json",
}


def _redis() -> Redis | None:
    """Redis 只是缓存层，连不上时退化成直连，不影响页面可用。"""
    try:
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = Redis.from_url(url, decode_responses=True, socket_timeout=2)
        client.ping()
        return client
    except Exception:  # noqa: BLE001
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(platform: str, payload: dict) -> list[dict]:
    items = []
    for index, raw in enumerate((payload or {}).get("items") or [], start=1):
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or raw.get("mobileUrl") or "").strip()
        if not title or not url.startswith("https://"):
            continue
        extra = raw.get("extra") or {}
        hot = str(extra.get("info") or "").strip()
        items.append({
            "platform": platform,
            "platform_zh": NAMES.get(platform, platform),
            "title": title[:300],
            "url": url[:600],
            "hot": hot[:40],
            "rank": index,
            "excerpt": str(extra.get("hover") or "")[:200],
        })
    return items


def fetch_platform(spec) -> dict:
    platform, timeout = spec
    started = time.time()
    try:
        response = requests.get(API_URL, params={"id": platform}, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        items = _normalize(platform, payload)
        return {"platform": platform, "ok": bool(items), "items": items,
                "seconds": round(time.time() - started, 1),
                "error": "" if items else "empty"}
    except Exception as exc:  # noqa: BLE001 - 单个平台失败不影响其它平台
        return {"platform": platform, "ok": False, "items": [], "seconds": round(time.time() - started, 1),
                "error": type(exc).__name__}


def _write_cache(runs: list[dict]) -> dict:
    client = _redis()
    platforms = []
    all_items = []
    for run in runs:
        if run["ok"]:
            if client is not None:
                client.set(KEY_ITEMS.format(platform=run["platform"]),
                           json.dumps(run["items"], ensure_ascii=False), ex=CACHE_TTL)
            all_items.extend(run["items"])
        platforms.append({"id": run["platform"], "name": NAMES.get(run["platform"], run["platform"]),
                          "count": len(run["items"]), "ok": run["ok"], "error": run["error"]})
    meta = {"updated_at": _now(), "source": API_URL, "ttl_seconds": CACHE_TTL,
            "platforms": platforms, "count": len(all_items)}
    if client is not None:
        client.set(KEY_META, json.dumps(meta, ensure_ascii=False), ex=CACHE_TTL * 2)
    return {"meta": meta, "items": all_items}


def _maybe_snapshot(items: list[dict]) -> int:
    """每小时落一份快照；Redis 里的小时标记保证同一小时只写一次。"""
    if not items:
        return 0
    client = _redis()
    hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    if client is not None and not client.set(KEY_HOUR, hour, nx=True, ex=7200):
        return 0
    try:
        with database.session_scope() as session:
            session.add_all([HotspotSnapshot(
                platform=item["platform"], title=item["title"], url=item["url"],
                hot=item["hot"], rank=item["rank"],
                captured_at=datetime.now(timezone.utc),
            ) for item in items])
        return len(items)
    except Exception as exc:  # noqa: BLE001 - 快照失败不影响页面
        logger.warning("hotspot snapshot failed: %s", exc)
        if client is not None:
            client.delete(KEY_HOUR)
        return 0


def prune(retention_days: int = RETENTION_DAYS) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    try:
        with database.session_scope() as session:
            result = session.execute(delete(HotspotSnapshot).where(HotspotSnapshot.captured_at < cutoff))
            return result.rowcount or 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("hotspot prune failed: %s", exc)
        return 0


def _collect(platforms=None) -> list[dict]:
    specs = [(pid, FETCH_TIMEOUT) for pid in (platforms or DEFAULT_PLATFORMS)]
    with ThreadPoolExecutor(max_workers=min(6, len(specs))) as pool:
        return list(pool.map(fetch_platform, specs))


def sync(platforms=None) -> dict:
    """拉取所有平台，写缓存，按小时落快照。"""
    started = time.time()
    client = _redis()
    if client is not None and not client.set(KEY_LOCK, "1", nx=True, ex=120):
        return {"status": "busy"}
    try:
        runs = _collect(platforms)
        written = _write_cache(runs)
        snapshot_rows = _maybe_snapshot(written["items"])
        if snapshot_rows:
            prune()
        summary = {
            "status": "ok",
            "platforms": {run["platform"]: len(run["items"]) for run in runs},
            "items": len(written["items"]),
            "snapshot_rows": snapshot_rows,
            "seconds": round(time.time() - started, 1),
        }
        logger.info("hotspot sync: %s", summary)
        return summary
    finally:
        if client is not None:
            client.delete(KEY_LOCK)


def _from_snapshot(platform: str | None) -> list[dict]:
    """上游与缓存都没数据时，退到最近一份 PG 快照。"""
    try:
        since = datetime.now(timezone.utc) - timedelta(days=2)
        with database.session_scope() as session:
            query = select(HotspotSnapshot).where(HotspotSnapshot.captured_at >= since)
            if platform:
                query = query.where(HotspotSnapshot.platform == platform)
            rows = session.execute(query.order_by(HotspotSnapshot.captured_at.desc()).limit(200)).scalars().all()
        seen = set()
        items = []
        for row in rows:
            if row.title in seen:
                continue
            seen.add(row.title)
            items.append({"platform": row.platform, "platform_zh": NAMES.get(row.platform, row.platform),
                          "title": row.title, "url": row.url or "", "hot": row.hot or "",
                          "rank": row.rank or 0, "excerpt": ""})
        return items
    except Exception as exc:  # noqa: BLE001
        logger.warning("hotspot snapshot read failed: %s", exc)
        return []


def load(platform: str = "", query: str = "", limit: int = 60) -> dict:
    client = _redis()
    wanted = [platform] if platform in NAMES else list(DEFAULT_PLATFORMS)
    meta, items = {}, []
    if client is not None:
        meta_raw = client.get(KEY_META)
        meta = json.loads(meta_raw) if meta_raw else {}
        for pid in wanted:
            raw = client.get(KEY_ITEMS.format(platform=pid))
            if raw:
                items.extend(json.loads(raw))
    global _LAST_ATTEMPT
    now = time.time()
    if not items and now - _LAST_ATTEMPT > 60:  # 冷启动或缓存过期：最多每分钟补一次
        _LAST_ATTEMPT = now
        if client is None:
            runs = _collect([platform] if platform in NAMES else None)
            items = [entry for run in runs if run["ok"] for entry in run["items"]]
            meta = {"updated_at": _now(), "degraded": not items,
                    "platforms": [{"id": run["platform"], "name": NAMES.get(run["platform"], run["platform"]),
                                   "count": len(run["items"]), "ok": run["ok"], "error": run["error"]}
                                  for run in runs]}
        else:
            sync()
            meta_raw = client.get(KEY_META)
            meta = json.loads(meta_raw) if meta_raw else meta
            for pid in wanted:
                raw = client.get(KEY_ITEMS.format(platform=pid))
                if raw:
                    items.extend(json.loads(raw))
    if not items:
        items = _from_snapshot(platform or None)
        if items:
            meta = {**meta, "degraded": True, "updated_at": meta.get("updated_at") or _now()}
    needle = query.strip().lower()
    if needle:
        items = [item for item in items
                 if needle in item["title"].lower() or needle in (item.get("excerpt") or "").lower()]
    if platform:
        items.sort(key=lambda item: item["rank"])
    else:
        # 全部视图按平台轮转交叉：否则前 30 条全是微博，看不出"广场"的感觉
        buckets: dict[str, list[dict]] = {}
        for item in items:
            buckets.setdefault(item["platform"], []).append(item)
        for rows in buckets.values():
            rows.sort(key=lambda item: item["rank"])
        outline = [pid for pid, _ in PLATFORMS if pid in buckets]
        mixed: list[dict] = []
        cursor = 0
        while len(mixed) < len(items) and cursor < 60:
            for pid in outline:
                if cursor < len(buckets[pid]):
                    mixed.append(buckets[pid][cursor])
            cursor += 1
        items = mixed
    counts: dict[str, int] = {}
    for item in items:
        counts[item["platform"]] = counts.get(item["platform"], 0) + 1
    platforms = [{"id": pid, "name": NAMES[pid], "count": counts.get(pid, 0), "ok": counts.get(pid, 0) > 0}
                 for pid in DEFAULT_PLATFORMS]
    return {"items": items[:limit], "meta": meta, "platforms": platforms}


@router.get("/api/hotspots")
def list_hotspots(platform: str = Query(default="", max_length=32),
                  q: str = Query(default="", max_length=80),
                  limit: int = Query(default=60, ge=1, le=400)):
    data = load(platform=platform, query=q, limit=limit)
    return {
        "items": data["items"],
        "updated_at": (data["meta"] or {}).get("updated_at"),
        "degraded": bool((data["meta"] or {}).get("degraded")),
        "platforms": data["platforms"],
    }


@router.get("/api/hotspots/meta")
def hotspots_meta():
    data = load(limit=0)
    return {"updated_at": (data["meta"] or {}).get("updated_at"),
            "ttl_seconds": CACHE_TTL,
            "platforms": (data["meta"] or {}).get("platforms") or []}


def _task():
    from .celery_app import celery_app

    @celery_app.task(name="hotspot.sync", max_retries=2, default_retry_delay=60)
    def hotspot_sync():
        return sync()

    return hotspot_sync


hotspot_sync_task = _task()

@router.get("/hotspots", include_in_schema=False)
def hotspots_page():
    from fastapi.responses import HTMLResponse

    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
