"""低粉爆文榜：只读本地快照 + 少量计费接口。

铁律：GET 接口永远不直连上游。上游只出现在 lowfans_sync（定时同步）
和下面 3 个计费 POST（实时刷新 / 导出 / 管理员补采）。

赛道说明：上游 wx_type 只读不可过滤（实测传参被静默忽略），且 `其他`
占近四成，所以赛道一律按本地分组展示，空缺的赛道保留 tab 但灰显。
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, or_, select

from . import accounts, database, lowfans_sync
from .models import LowfansArticle, LowfansSyncRun

router = APIRouter()

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
DEFAULT_RANGE = lowfans_sync.DEFAULT_RANGE
OTHER_LABEL = "其他"
EXPORT_LIMIT = 200
GETRK_URL = os.getenv("WXRANK_GETRK_URL", "http://data.wxrank.com/weixin/getrk")

# 上游 24 个官方赛道（顺序即前端 tab 顺序），外加我们归并出来的「其他」
CATEGORIES = [
    "财经", "时事", "科技", "教育", "健康", "娱乐", "生活", "文化",
    "职场", "商业", "汽车", "房产", "体育", "军事", "法律", "政务",
    "科学", "母婴", "情感", "读书", "摄影", "设计", "农业", "宗教",
    OTHER_LABEL,
]

PUBLIC_FIELDS = (
    "art_id", "rank_no", "wx_name", "wx_type", "avatar", "title", "art_url",
    "publish_name", "pub_time", "read_num", "like_num", "look_num", "share_num",
    "comment_num", "boost_ratio", "burst_score", "account_read_base",
    "account_read_avg", "account_read_median", "account_read_max", "stats_range",
    "wx_biz", "stat_date",
)


def _norm_type(value: str | None) -> str:
    """空分类并入「其他」，与前端 tab 对齐。"""
    text = (value or "").strip()
    return text or OTHER_LABEL


def _public(row: LowfansArticle) -> dict[str, Any]:
    payload = {field: getattr(row, field, None) for field in PUBLIC_FIELDS}
    payload["wx_type"] = _norm_type(row.wx_type)
    payload["boost_ratio"] = round(float(row.boost_ratio or 0), 2)
    payload["burst_score"] = round(float(row.burst_score or 0), 2)
    return payload


def _latest_date(session) -> str:
    return session.execute(
        select(LowfansArticle.stat_date).where(LowfansArticle.range_type == DEFAULT_RANGE)
        .order_by(LowfansArticle.stat_date.desc()).limit(1)
    ).scalar() or ""


def _dates(session, limit: int = 30) -> list[str]:
    rows = session.execute(
        select(LowfansArticle.stat_date).where(LowfansArticle.range_type == DEFAULT_RANGE)
        .group_by(LowfansArticle.stat_date)
        .order_by(LowfansArticle.stat_date.desc()).limit(limit)
    ).scalars().all()
    return [str(value) for value in rows]


def _category_counts(session, stat_date: str) -> dict[str, int]:
    rows = session.execute(
        select(LowfansArticle.wx_type, func.count())
        .where(LowfansArticle.stat_date == stat_date,
               LowfansArticle.range_type == DEFAULT_RANGE)
        .group_by(LowfansArticle.wx_type)
    ).all()
    counts: dict[str, int] = {}
    for wx_type, count in rows:
        label = _norm_type(wx_type)
        counts[label] = counts.get(label, 0) + int(count or 0)
    return counts


def _categories_payload(counts: dict[str, int]) -> list[dict[str, Any]]:
    ordered = [name for name in CATEGORIES if counts.get(name)]
    extra = [name for name in counts if name not in CATEGORIES]
    return [{"name": name, "count": counts.get(name, 0)} for name in ordered + sorted(extra)]


# ---------------------------------------------------------------- 页面
@router.get("/lowfans", response_class=HTMLResponse, include_in_schema=False)
def lowfans_page():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as handle:
        html = handle.read()
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- 只读 API
@router.get("/api/lowfans")
def list_lowfans(
    wx_type: str = Query(default="", max_length=32),
    q: str = Query(default="", max_length=80),
    sort: str = Query(default="burst", pattern="^(burst|read|boost|time)$"),
    date: str = Query(default="", max_length=10),
    page: int = Query(default=1, ge=1, le=500),
    page_size: int = Query(default=50, ge=1, le=100),
):
    with database.session_scope() as session:
        stat_date = date.strip() or _latest_date(session)
        if not stat_date:
            return {"items": [], "total": 0, "page": page, "page_size": page_size,
                    "stat_date": "", "range": DEFAULT_RANGE, "categories": [],
                    "degraded": True, "reason": "尚未同步任何榜单"}
        base = [LowfansArticle.stat_date == stat_date,
                LowfansArticle.range_type == DEFAULT_RANGE]
        conditions = list(base)
        if wx_type.strip():
            label = wx_type.strip()
            if label == OTHER_LABEL:
                conditions.append(or_(LowfansArticle.wx_type == "",
                                      LowfansArticle.wx_type == OTHER_LABEL))
            else:
                conditions.append(LowfansArticle.wx_type == label)
        needle = q.strip()
        if needle:
            like = f"%{needle}%"
            conditions.append(or_(LowfansArticle.title.ilike(like),
                                  LowfansArticle.wx_name.ilike(like)))
        total = session.execute(select(func.count()).select_from(LowfansArticle)
                                .where(*conditions)).scalar() or 0
        order = {
            "burst": LowfansArticle.rank_no.asc(),
            "read": LowfansArticle.read_num.desc(),
            "boost": LowfansArticle.boost_ratio.desc(),
            "time": LowfansArticle.pub_time.desc(),
        }[sort]
        rows = session.execute(
            select(LowfansArticle).where(*conditions).order_by(order, LowfansArticle.rank_no)
            .offset((page - 1) * page_size).limit(page_size)
        ).scalars().all()
        counts = _category_counts(session, stat_date)
        dates = _dates(session)
        last = session.execute(
            select(LowfansSyncRun).order_by(LowfansSyncRun.started_at.desc()).limit(1)
        ).scalars().first()
    latest_ok = bool(last and last.status == "ok")
    items = [_public(row) for row in rows]
    return {
        "items": items,
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "pages": max(1, (int(total) + page_size - 1) // page_size),
        "stat_date": stat_date,
        "range": DEFAULT_RANGE,
        "categories": _categories_payload(counts),
        "dates": dates,
        "degraded": not latest_ok,
        "last_sync": {"status": getattr(last, "status", "") or "",
                      "started_at": last.started_at.isoformat() if last and last.started_at else None,
                      "inserted": getattr(last, "inserted", 0) or 0,
                      "error": (getattr(last, "error", "") or "")[:200]},
    }


@router.get("/api/lowfans/meta")
def lowfans_meta():
    with database.session_scope() as session:
        stat_date = _latest_date(session)
        counts = _category_counts(session, stat_date) if stat_date else {}
        dates = _dates(session)
        total = session.execute(select(func.count()).select_from(LowfansArticle)
                                .where(LowfansArticle.stat_date == stat_date,
                                       LowfansArticle.range_type == DEFAULT_RANGE)
                                ).scalar() if stat_date else 0
    return {
        "stat_date": stat_date,
        "range": DEFAULT_RANGE,
        "total": int(total or 0),
        "dates": dates,
        "categories": _categories_payload(counts),
        "pages_per_day": lowfans_sync.pages_per_day(),
        "configured": bool(lowfans_sync.api_key()),
        "last_sync": lowfans_sync.last_run(),
    }


@router.get("/api/lowfans/{art_id}")
def lowfans_detail(art_id: str):
    with database.session_scope() as session:
        row = session.execute(
            select(LowfansArticle).where(LowfansArticle.art_id == art_id)
            .order_by(LowfansArticle.stat_date.desc()).limit(1)
        ).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="没有这篇记录")
        payload = _public(row)
        siblings = session.execute(
            select(LowfansArticle)
            .where(LowfansArticle.wx_biz == row.wx_biz,
                   LowfansArticle.art_id != row.art_id,
                   LowfansArticle.stat_date == row.stat_date)
            .order_by(LowfansArticle.rank_no).limit(8)
        ).scalars().all()
    payload["account_siblings"] = [_public(item) for item in siblings]
    payload["account"] = {
        "wx_name": row.wx_name, "wx_type": _norm_type(row.wx_type),
        "avatar": row.avatar, "read_base": row.account_read_base,
        "read_avg": row.account_read_avg, "read_median": row.account_read_median,
        "read_max": row.account_read_max, "stats_range": row.stats_range,
    }
    return payload


# ---------------------------------------------------------------- 计费接口
@router.post("/api/lowfans/refresh")
def refresh_metrics(payload: dict):
    """实时刷新一篇的互动数（上游 getrk 2 分/次，我们收 3 积分）。

    路径用固定 `/api/lowfans/refresh` 而不是 `/{art_id}/refresh`：计费中间件
    按 pricing_rules.path 精确匹配，带占位符的模板匹配不上。
    """
    art_id = str(payload.get("art_id") or "").strip()[:64]
    if not art_id:
        raise HTTPException(status_code=400, detail="缺少 art_id")
    key = lowfans_sync.api_key()
    if not key:
        raise HTTPException(status_code=503, detail="数据源未配置")
    with database.session_scope() as session:
        row = session.execute(
            select(LowfansArticle).where(LowfansArticle.art_id == art_id)
            .order_by(LowfansArticle.stat_date.desc()).limit(1)
        ).scalars().first()
        if row is None:
            raise HTTPException(status_code=404, detail="没有这篇记录")
        url, stat_date = row.art_url, row.stat_date
    try:
        response = requests.post(GETRK_URL, json={"key": key, "url": url}, timeout=(5, 25))
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"实时取数失败：{type(exc).__name__}") from exc
    if int(payload.get("code") or 0) != 0:
        raise HTTPException(status_code=502, detail=str(payload.get("msg") or "上游返回错误"))
    data = payload.get("data") or {}
    updated = {
        "read_num": int(data.get("read_num") or 0),
        "like_num": int(data.get("like_num") or 0),
        "look_num": int(data.get("look_num") or 0),
        "share_num": int(data.get("share_num") or 0),
        "comment_num": int(data.get("comment_count") or 0),
    }
    with database.session_scope() as session:
        row = session.execute(
            select(LowfansArticle).where(LowfansArticle.art_id == art_id,
                                         LowfansArticle.stat_date == stat_date)
        ).scalars().first()
        if row is not None:
            for field, value in updated.items():
                if value:
                    setattr(row, field, value)
            if row.account_read_base:
                row.boost_ratio = round(row.read_num / row.account_read_base, 4)
    return {"status": "success", "art_id": art_id, "metrics": updated}


@router.post("/api/lowfans/export")
def export_csv(payload: dict):
    """按当前筛选导出一份 CSV，最多 200 行。"""
    wx_type = str(payload.get("wx_type") or "").strip()[:32]
    q = str(payload.get("q") or "").strip()[:80]
    sort = str(payload.get("sort") or "burst")
    date = str(payload.get("date") or "").strip()[:10]
    if sort not in {"burst", "read", "boost", "time"}:
        sort = "burst"
    with database.session_scope() as session:
        stat_date = date or _latest_date(session)
        if not stat_date:
            raise HTTPException(status_code=404, detail="尚未同步任何榜单")
        conditions = [LowfansArticle.stat_date == stat_date,
                      LowfansArticle.range_type == DEFAULT_RANGE]
        if wx_type:
            if wx_type == OTHER_LABEL:
                conditions.append(or_(LowfansArticle.wx_type == "",
                                      LowfansArticle.wx_type == OTHER_LABEL))
            else:
                conditions.append(LowfansArticle.wx_type == wx_type)
        if q:
            like = f"%{q}%"
            conditions.append(or_(LowfansArticle.title.ilike(like),
                                  LowfansArticle.wx_name.ilike(like)))
        order = {
            "burst": LowfansArticle.rank_no.asc(),
            "read": LowfansArticle.read_num.desc(),
            "boost": LowfansArticle.boost_ratio.desc(),
            "time": LowfansArticle.pub_time.desc(),
        }[sort]
        rows = session.execute(
            select(LowfansArticle).where(*conditions).order_by(order).limit(EXPORT_LIMIT)
        ).scalars().all()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["排名", "标题", "公众号", "赛道", "发布时间", "阅读", "点赞",
                     "在看", "分享", "留言", "爆发倍率", "爆文分", "阅读基线", "原文链接"])
    for row in rows:
        writer.writerow([
            row.rank_no, row.title, row.wx_name, _norm_type(row.wx_type),
            row.pub_time or "", row.read_num, row.like_num, row.look_num,
            row.share_num, row.comment_num, f"{float(row.boost_ratio or 0):.2f}",
            f"{float(row.burst_score or 0):.2f}", row.account_read_base, row.art_url,
        ])
    filename = f"lowfans-{stat_date}-{wx_type or 'all'}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/api/admin/lowfans/sync")
def admin_sync(request: Request, pages: int | None = Query(default=None, ge=1, le=135),
               date: str = Query(default="", max_length=10)):
    accounts.require_admin(request)
    result = lowfans_sync.sync_daily(pages=pages, stat_date=date.strip() or None)
    return {"status": "success", "sync": result}
