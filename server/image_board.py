"""低分爆图：资源库贴图（content_type=book）候选榜。

- 数据源：微小榜资源库 artlist，content_type=book，1 积分/次，每页 20 条。
- 页面只读本地快照；上游在管理员手动采集，或显式开启 IMAGE_BOARD_SYNC_ENABLED=1
  后由 beat 定时调用（默认关闭，不自动花钱）。超过 IMAGE_BOARD_STALE_HOURS 未成功
  同步即标记 degraded，页面不得称为实时榜单。
- book 里混有新闻和图文，所以每条在读取时打「图为主 / 图文」标签：
  正文字数 ≤ IMAGE_FIRST_MAX_WORDS 且无视频 → 图为主。这是规则判断，不是人工核验。
- 与低粉爆文榜按文章 sn（= 低粉榜 art_id）匹配，匹配到才显示爆发倍率；
  没匹配到不代表不是低粉，只代表不在已同步的低粉榜里。
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import delete, func, or_, select

from . import accounts, database
from . import viral_insights_membership as membership
from .models import ImageBoardItem, ImageBoardSyncRun, LowfansArticle

logger = logging.getLogger(__name__)
router = APIRouter()

ARTLIST_URL = os.getenv("WXRANK_ARTLIST_URL", "http://data.wxrank.com/weixin/artlist")
POINTS_PER_CALL = 1
BASE_PAGES = 10                # 日常读取最多 10 页，再按需要扩展
MAX_PAGES = 30                 # 单次上游调用预算上限（每成功页 1 积分）
MIN_READ = 10000
TARGET_HIGH_READ = 100
IMAGE_FIRST_MAX_WORDS = 100
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
OTHER_LABEL = "其他"

PUBLIC_FIELDS = (
    "sn", "wx_biz", "wx_type", "title", "art_url", "pic_url", "pub_time", "read_num",
    "like_num", "look_num", "share_num", "word_num", "image_num", "video_num", "stat_date",
)


def init_schema() -> None:
    from .models import Base
    # The matcher reads the existing lowfans snapshot; initialize both feature
    # tables when this module is loaded in a local/test process by itself.
    from . import lowfans_sync
    lowfans_sync.init_schema()
    Base.metadata.create_all(database.ENGINE,
                             tables=[ImageBoardItem.__table__, ImageBoardSyncRun.__table__],
                             checkfirst=True)


def _int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _row(stat_date: str, raw: dict) -> dict:
    return {
        "stat_date": stat_date,
        "sn": str(raw.get("sn") or "")[:64],
        "wx_biz": str(raw.get("wx_biz") or "")[:64],
        "wx_type": str(raw.get("wx_type") or "").strip()[:32],
        "content_type": str(raw.get("content_type") or "book")[:16],
        "title": str(raw.get("title") or ""),
        "content": str(raw.get("content") or "")[:4000],
        "art_url": str(raw.get("art_url") or ""),
        "pic_url": str(raw.get("pic_url") or ""),
        "pub_time": str(raw.get("pub_time") or "")[:32] or None,
        "ip_region": str(raw.get("ip_region") or "")[:32],
        "copyright": str(raw.get("copyright") or "")[:16],
        "read_num": _int(raw.get("read_num")),
        "like_num": _int(raw.get("like_num")),
        "look_num": _int(raw.get("look_num")),
        "share_num": _int(raw.get("share_num")),
        "word_num": _int(raw.get("word_num")),
        "image_num": _int(raw.get("image_num")),
        "video_num": _int(raw.get("video_num")),
        "qmusic_num": _int(raw.get("qmusic_num")),
        "data_update_time": str(raw.get("data_update_time") or "")[:32] or None,
    }


def store(stat_date: str, raw_items: list[dict], *, source: str, pages_ok: int = 0,
          cost_points: int = 0, upstream_total: int = 0, error: str = "") -> dict:
    """整日替换快照并写审计。只收 content_type=book 的条目。"""
    rows, seen = [], set()
    for raw in raw_items:
        item = _row(stat_date, raw)
        if not item["sn"] or item["sn"] in seen or item["content_type"] != "book":
            continue
        seen.add(item["sn"])
        rows.append(item)
    with database.session_scope() as session:
        existing = session.execute(select(func.count()).select_from(ImageBoardItem)
                                   .where(ImageBoardItem.stat_date == stat_date)).scalar() or 0
        # Never replace a more complete snapshot with a failed or smaller pull.
        replace = bool(rows) and (not existing or (not error and len(rows) >= existing))
        if replace:
            session.execute(delete(ImageBoardItem).where(ImageBoardItem.stat_date == stat_date))
            session.add_all(ImageBoardItem(**item) for item in rows)
        session.add(ImageBoardSyncRun(
            finished_at=datetime.now(timezone.utc), stat_date=stat_date, source=source,
            pages_ok=pages_ok, cost_points=cost_points, inserted=len(rows) if replace else 0,
            upstream_total=upstream_total,
            status="ok" if replace and not error else ("partial" if rows else "failed"),
            error=error[:2000] or None))
    return {"stat_date": stat_date, "inserted": len(rows) if replace else 0,
            "retained": existing if not replace else 0, "pages_ok": pages_ok,
            "cost_points": cost_points, "upstream_total": upstream_total, "error": error}


def sync(stat_date: str, pages: int = BASE_PAGES, *, extended_pages: int | None = None) -> dict:
    """按指定日期和阅读数降序采集；确有可能凑够万阅内容时才扩页。"""
    key = os.getenv("WXRANK_API_KEY", "").strip()
    if not key:
        return {"status": "unconfigured", "error": "WXRANK_API_KEY 未配置"}
    day = stat_date.replace("-", "")
    pages = max(1, min(MAX_PAGES, pages))
    budget = max(pages, min(MAX_PAGES, extended_pages or pages))
    items: list[dict] = []
    cursor, pages_ok, total, error = None, 0, 0, ""
    for page in range(1, budget + 1):
        payload = {"key": key, "cursor": cursor} if cursor else {
            "key": key, "date": day, "content_type": "book", "sort": "read_num"}
        try:
            response = requests.post(ARTLIST_URL, json=payload, timeout=(5, 30))
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            error = f"page {page}: {type(exc).__name__}"
            break
        if _int(body.get("code")) != 0 or body.get("code") is None:
            error = f"page {page}: code={body.get('code')}"
            break
        pages_ok += 1
        data = body.get("data") or {}
        total = _int(data.get("total")) or total
        batch = data.get("list") or []
        items.extend(batch)
        cursor = data.get("cursor")
        if not cursor or not batch:
            break
        if page >= pages:
            qualified = {str(item.get('sn')) for item in items if item.get('sn')
                         and str(item.get('content_type') or 'book') == 'book'
                         and _int(item.get('read_num')) >= MIN_READ}
            # The upstream orders by read count descending. Once a valid item is
            # below the threshold, later pages cannot add qualifying entries.
            reached_below = any(_int(item.get('read_num')) < MIN_READ for item in batch)
            if len(qualified) >= TARGET_HIGH_READ or reached_below:
                break
        time.sleep(0.15)
    result = store(stat_date, items, source="api", pages_ok=pages_ok,
                   cost_points=pages_ok * POINTS_PER_CALL, upstream_total=total, error=error)
    result["status"] = "ok" if result["inserted"] and not error else ("partial" if result["inserted"] or result["retained"] else "failed")
    return result


def sync_enabled() -> bool:
    """定时同步默认关闭：上游按页计费，需显式开启 IMAGE_BOARD_SYNC_ENABLED=1。"""
    return os.getenv("IMAGE_BOARD_SYNC_ENABLED", "0").strip() == "1"


def sync_pages() -> int:
    try:
        return max(1, min(MAX_PAGES, int(os.getenv("IMAGE_BOARD_SYNC_PAGES", str(BASE_PAGES)))))
    except ValueError:
        return BASE_PAGES


def stale_after_hours() -> int:
    try:
        return max(6, int(os.getenv("IMAGE_BOARD_STALE_HOURS", "48")))
    except ValueError:
        return 48


def min_complete_items() -> int:
    """低于这个条数视为“上游当天还没生成完”，允许后续调度重试。"""
    try:
        return max(1, int(os.getenv("IMAGE_BOARD_MIN_ITEMS", "20")))
    except ValueError:
        return 20


def max_attempts() -> int:
    """同一天最多尝试几次，给真正冷清的日期一个成本上限。"""
    try:
        return max(1, min(6, int(os.getenv("IMAGE_BOARD_MAX_ATTEMPTS", "3"))))
    except ValueError:
        return 3


def scheduled_sync() -> dict:
    """定时任务入口：同步昨日（北京时间）贴图。

    上游按发布日生成数据，当天越早抓越可能只拿到几条。所以“已同步过”不足以
    判定完成：条数低于阈值时允许后续调度重试（store 会整日替换，不会重复），
    同时用尝试次数上限兜住成本。
    """
    if not sync_enabled():
        return {"status": "disabled"}
    from datetime import timedelta
    beijing = timezone(timedelta(hours=8))
    stat_date = (datetime.now(beijing) - timedelta(days=1)).strftime("%Y-%m-%d")
    with database.session_scope() as session:
        existing = session.execute(select(func.count()).select_from(ImageBoardItem)
                                   .where(ImageBoardItem.stat_date == stat_date)).scalar() or 0
        high_read = session.execute(select(func.count()).select_from(ImageBoardItem)
                                   .where(ImageBoardItem.stat_date == stat_date,
                                          ImageBoardItem.read_num >= MIN_READ)).scalar() or 0
        attempts = session.execute(select(func.count()).select_from(ImageBoardSyncRun)
                                   .where(ImageBoardSyncRun.stat_date == stat_date)).scalar() or 0
    if existing >= min(200, sync_pages() * 20) and high_read >= TARGET_HIGH_READ:
        return {"status": "cached", "stat_date": stat_date, "inserted": int(existing)}
    if attempts >= max_attempts():
        return {"status": "cached", "stat_date": stat_date, "inserted": int(existing),
                "reason": "已达到本日尝试次数上限"}
    # 失败只写 sync_runs，不清空旧快照（store 仅在拿到数据时整日替换）。
    return sync(stat_date, sync_pages(), extended_pages=MAX_PAGES)


def freshness(session, stat_date: str) -> dict:
    """最近一次成功同步距今多久；超过阈值标记 stale，页面不能称为实时榜单。"""
    last_ok = session.execute(select(ImageBoardSyncRun).where(ImageBoardSyncRun.status.in_(("ok", "partial")))
                              .order_by(ImageBoardSyncRun.id.desc()).limit(1)).scalars().first()
    if not last_ok or not last_ok.finished_at:
        return {"stale": True, "last_success_at": None, "stale_after_hours": stale_after_hours()}
    finished = last_ok.finished_at if last_ok.finished_at.tzinfo else last_ok.finished_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    age_hours = (now - finished).total_seconds() / 3600
    from datetime import timedelta
    expected = (now.astimezone(timezone(timedelta(hours=8))) - timedelta(days=1)).date().isoformat()
    return {"stale": age_hours > stale_after_hours() or stat_date < expected, "last_success_at": finished.isoformat(),
            "age_hours": round(age_hours, 1), "stale_after_hours": stale_after_hours()}


def is_image_first(item: ImageBoardItem) -> bool:
    return item.word_num <= IMAGE_FIRST_MAX_WORDS and item.video_num == 0 and item.image_num > 0


def _latest_date(session) -> str:
    return session.execute(select(ImageBoardItem.stat_date)
                           .order_by(ImageBoardItem.stat_date.desc()).limit(1)).scalar() or ""


def _lowfans_matches(session, sns: list[str]) -> dict[str, dict]:
    if not sns:
        return {}
    matches: dict[str, dict] = {}
    for start in range(0, len(sns), 500):
        rows = session.execute(
            select(LowfansArticle).where(LowfansArticle.art_id.in_(sns[start:start + 500]))
            .order_by(LowfansArticle.stat_date.desc())).scalars()
        for row in rows:
            matches.setdefault(row.art_id, {
                "wx_name": row.wx_name, "boost_ratio": round(float(row.boost_ratio or 0), 2),
                "account_read_base": row.account_read_base, "stat_date": row.stat_date})
    return matches


# ---------------------------------------------------------------- 页面
@router.get("/image-board", response_class=HTMLResponse, include_in_schema=False)
def image_board_page():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as handle:
        return HTMLResponse(handle.read(), headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- 封面代理
# 微信图片有防盗链：浏览器直连 mmbiz.qpic.cn 会拿到 403 或空图，页面只剩灰块。
# 由服务端带 Referer 取一次字节再回给前端，顺带避开用户侧跨域限制。
COVER_HOSTS = ("mmbiz.qpic.cn", "mmecoa.qpic.cn", "mmbiz.qlogo.cn")
COVER_CACHE: dict[str, tuple[float, bytes, str]] = {}
COVER_TTL = 6 * 3600
COVER_MAX_ENTRIES = 400


def _cover_fetch(url: str) -> tuple[bytes, str] | None:
    from urllib.parse import urlsplit

    if urlsplit(url).hostname not in COVER_HOSTS:
        return None
    try:
        response = requests.get(url, timeout=(5, 15), headers={
            "Referer": "https://mp.weixin.qq.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        })
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("image board cover fetch failed: %s", type(exc).__name__)
        return None
    content_type = (response.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    if not content_type.startswith("image/"):
        return None
    return response.content, content_type


@router.get("/api/image-board/cover")
def cover(request: Request, sn: str = Query(..., min_length=1, max_length=64)):
    """按文章 sn 取封面；启用会员访问时仅有权益者可取。"""
    membership.require_access(request)
    with database.session_scope() as session:
        row = session.execute(select(ImageBoardItem).where(ImageBoardItem.sn == sn)
                              .order_by(ImageBoardItem.stat_date.desc()).limit(1)).scalars().first()
        if row is None or not row.pic_url:
            raise HTTPException(status_code=404, detail="没有封面")
        url = row.pic_url
    return _serve_cover(sn, url)


def _serve_cover(sn: str, url: str):
    now = time.time()
    cached = COVER_CACHE.get(sn)
    if cached and now - cached[0] < COVER_TTL:
        return Response(cached[1], media_type=cached[2],
                        headers={"Cache-Control": "private, no-store" if membership.enabled() else "public, max-age=86400"})
    fetched = _cover_fetch(url)
    if fetched is None:
        raise HTTPException(status_code=502, detail="封面获取失败")
    payload, content_type = fetched
    if len(COVER_CACHE) >= COVER_MAX_ENTRIES:
        oldest = min(COVER_CACHE, key=lambda key: COVER_CACHE[key][0])
        COVER_CACHE.pop(oldest, None)
    COVER_CACHE[sn] = (now, payload, content_type)
    return Response(payload, media_type=content_type,
                    headers={"Cache-Control": "private, no-store" if membership.enabled() else "public, max-age=86400"})


def _board_pool(session, stat_date: str) -> list[ImageBoardItem]:
    candidates = session.execute(select(ImageBoardItem)
        .where(ImageBoardItem.stat_date <= stat_date)
        .order_by(ImageBoardItem.stat_date.desc(), ImageBoardItem.read_num.desc(),
                  ImageBoardItem.sn.asc())).scalars()
    rows, seen = [], set()
    for row in candidates:
        if row.sn in seen:
            continue
        rows.append(row)
        seen.add(row.sn)
    return rows


def _read_rank(row):
    return (row.read_num >= MIN_READ, row.stat_date, row.read_num, row.share_num, row.sn)


@router.get("/api/image-board/preview-cover")
def preview_cover(index: int = Query(..., ge=1, le=10)):
    """Only the fixed, latest preview slots are public; no arbitrary image IDs."""
    if index > membership.preview_limit():
        raise HTTPException(status_code=404, detail="预览图片不存在")
    with database.session_scope() as session:
        stat_date = _latest_date(session)
        rows = _board_pool(session, stat_date) if stat_date else []
        rows.sort(key=_read_rank, reverse=True)
        row = rows[index - 1] if len(rows) >= index else None
        if row is None or not row.pic_url:
            raise HTTPException(status_code=404, detail="没有封面")
        sn, url = row.sn, row.pic_url
    return _serve_cover(sn, url)


# ---------------------------------------------------------------- 只读 API
@router.get("/api/image-board")
def list_items(
    request: Request,
    wx_type: str = Query(default="", max_length=32),
    q: str = Query(default="", max_length=80),
    sort: str = Query(default="read", pattern="^(read|time|share)$"),
    scope: str = Query(default="all", pattern="^(image|all|lowfans)$"),
    date: str = Query(default="", max_length=10),
):
    accessible = not membership.enabled() or membership.has_access(
        (getattr(request.state, "user", None) or {}).get("id"))
    if not accessible:
        scope, sort, date, wx_type, q = "all", "read", "", "", ""
    with database.session_scope() as session:
        stat_date = date.strip() or _latest_date(session)
        if not stat_date:
            return {"items": [], "total": 0, "stat_date": "", "categories": [], "counts": {},
                    "degraded": True, "reason": "尚未采集任何贴图数据"}
        # Combine the selected date and earlier snapshots without a 200-item
        # cutoff. Repeated articles use their newest available snapshot.
        rows = _board_pool(session, stat_date)
        primary_count = sum(row.stat_date == stat_date for row in rows)
        fallback_count = len(rows) - primary_count
        matches = _lowfans_matches(session, [row.sn for row in rows])
        last = session.execute(select(ImageBoardSyncRun).order_by(ImageBoardSyncRun.id.desc())
                               .limit(1)).scalars().first()
        dates = session.execute(select(ImageBoardItem.stat_date).group_by(ImageBoardItem.stat_date)
                                .order_by(ImageBoardItem.stat_date.desc()).limit(30)).scalars().all()
        fresh = freshness(session, stat_date)

    counts = {"all": len(rows), "image": sum(is_image_first(r) for r in rows),
              "lowfans": sum(r.sn in matches for r in rows)}
    if scope == "image":
        rows = [r for r in rows if is_image_first(r)]
    elif scope == "lowfans":
        rows = [r for r in rows if r.sn in matches]
    categories: dict[str, int] = {}
    for row in rows:
        label = row.wx_type or OTHER_LABEL
        categories[label] = categories.get(label, 0) + 1
    if wx_type.strip():
        rows = [r for r in rows if (r.wx_type or OTHER_LABEL) == wx_type.strip()]
    needle = q.strip().lower()
    if needle:
        rows = [r for r in rows if needle in (r.title or "").lower()]
    key = {"read": _read_rank,
           "share": lambda r: (r.read_num >= MIN_READ, r.stat_date, r.share_num, r.read_num, r.sn),
           "time": lambda r: (r.read_num >= MIN_READ, r.stat_date, r.pub_time or "", r.sn)}[sort]
    rows.sort(key=key, reverse=True)

    if not accessible:
        preview = [{"rank_no": i + 1, "wx_type": row.wx_type or OTHER_LABEL,
                    "title_preview": (row.title or "")[:18] + ("…" if len(row.title or "") > 18 else ""),
                    "stat_date": row.stat_date,
                    "cover_url": f"/api/image-board/preview-cover?index={i + 1}" if row.pic_url else ""}
                   for i, row in enumerate(rows[:membership.preview_limit()])]
        last_sync = {"status": last.status, "inserted": last.inserted} if last else {}
        return {"items": preview, "total": len(preview), "stat_date": stat_date,
                "counts": counts,
                "categories": [{"name": k, "count": v} for k, v in categories.items()],
                "last_sync": last_sync, "preview": True, "membership_required": True,
                "freshness": fresh, "degraded": fresh["stale"],
                "primary_count": primary_count, "fallback_count": fallback_count,
                "reason": "榜单未更新至最近日期，当前展示最近可用数据" if fresh["stale"] else ""}
    items: list[dict[str, Any]] = []
    for rank, row in enumerate(rows, 1):
        payload = {field: getattr(row, field) for field in PUBLIC_FIELDS}
        payload["wx_type"] = row.wx_type or OTHER_LABEL
        payload["rank_no"] = rank
        payload["is_fallback"] = row.stat_date != stat_date
        payload["image_first"] = is_image_first(row)
        payload["excerpt"] = (row.content or "").strip()[:120]
        payload["cover_url"] = f"/api/image-board/cover?sn={row.sn}" if row.pic_url else ""
        payload["lowfans"] = matches.get(row.sn)
        items.append(payload)
    return {
        "items": items, "total": len(items), "stat_date": stat_date, "dates": list(dates),
        "primary_count": primary_count, "fallback_count": fallback_count,
        "counts": counts, "image_first_max_words": IMAGE_FIRST_MAX_WORDS,
        "categories": [{"name": k, "count": v} for k, v in
                       sorted(categories.items(), key=lambda kv: (kv[0] == OTHER_LABEL, -kv[1]))],
        "last_sync": {"source": last.source, "pages_ok": last.pages_ok, "cost_points": last.cost_points,
                      "inserted": last.inserted, "upstream_total": last.upstream_total,
                      "status": last.status} if last else {},
        "freshness": fresh,
        "degraded": fresh["stale"],
        "reason": "榜单未更新至最近日期，当前展示最近可用数据" if fresh["stale"] else "",
    }


# ---------------------------------------------------------------- 管理员（花钱）
@router.post("/api/admin/image-board/sync")
def admin_sync(request: Request, date: str = Query(..., min_length=8, max_length=10),
               pages: int = Query(default=BASE_PAGES, ge=1, le=MAX_PAGES)):
    accounts.require_admin(request)
    stat_date = date if "-" in date else f"{date[:4]}-{date[4:6]}-{date[6:8]}"
    return {"status": "success", "sync": sync(stat_date, pages)}


def _task():
    from .celery_app import celery_app

    @celery_app.task(name="image_board.sync", max_retries=0)
    def image_board_sync():
        # 失败不抛：旧快照保留，页面按 freshness 降级展示。
        try:
            return scheduled_sync()
        except Exception as exc:  # noqa: BLE001
            logger.warning("image board scheduled sync failed: %s", type(exc).__name__)
            return {"status": "failed", "error": type(exc).__name__}

    return image_board_sync


image_board_sync_task = _task()
