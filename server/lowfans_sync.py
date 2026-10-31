"""低粉爆文榜 —— 把微小榜 lowfans 榜单同步成本地快照。

设计约束（沿用 AI 超市 / 热点广场那套）：

- 页面只读本地 PG，永不直连上游；上游只出现在本模块和 lowfans.py 的计费接口里。
- 上游按次计费（5 积分 / 页 = 0.05 元），同步深度由 LOWFANS_PAGES_PER_DAY 控制。
  2026-10-31 实测：7d 榜单 total=6727、共 135 页；翻到第 7 页（350 条）即可覆盖
  全部 24 个赛道，所以默认 11 页（550 条）留出长尾冗余。
- 只做 7d 单窗口。赛道上游不支持过滤（实测传 wx_type 被静默忽略），
  只能拉回来本地按 wx_type 分组。
- 任何失败都不向上抛，写进 lowfans_sync_runs，由页面降级展示。
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone

import requests
from redis import Redis
from sqlalchemy import delete, func, select

from . import database
from .models import LowfansArticle, LowfansSyncRun

logger = logging.getLogger(__name__)

LOWFANS_URL = os.getenv("WXRANK_LOWFANS_URL", "http://data.wxrank.com/weixin/lowfans")
DEFAULT_RANGE = os.getenv("LOWFANS_RANGE", "7d")
PAGE_SIZE = 50
POINTS_PER_CALL = 5
FETCH_TIMEOUT = (5, 30)
KEY_LOCK = "lowfans:v1:sync:lock"
RETENTION_DAYS = max(7, int(os.getenv("LOWFANS_RETENTION_DAYS", "45")))
BEIJING = timezone(timedelta(hours=8))


def api_key() -> str:
    return os.getenv("WXRANK_API_KEY", "").strip()


def init_schema() -> None:
    """幂等建表。

    生产库的建表路径是模块自己的 init_schema，不是 alembic：deploy.sh 用
    `up -d --no-deps` 起服务，compose 里的 migrate 服务根本不会跑。这里用
    tables= 只 create 本模块的两张表，避免连带处理 users 等既有表。
    """
    from .models import Base

    Base.metadata.create_all(
        database.ENGINE,
        tables=[LowfansArticle.__table__, LowfansSyncRun.__table__],
        checkfirst=True,
    )


def pages_per_day() -> int:
    """每天翻多少页。11 页 = 550 条 = 55 积分 = 0.55 元/天。"""
    try:
        return max(1, min(135, int(os.getenv("LOWFANS_PAGES_PER_DAY", "11"))))
    except (TypeError, ValueError):
        return 11


def yesterday_beijing() -> str:
    """榜单统计日默认昨日（上游每日生成前一天榜单）。"""
    return (datetime.now(BEIJING) - timedelta(days=1)).strftime("%Y-%m-%d")


def _redis() -> Redis | None:
    try:
        client = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"),
                                decode_responses=True, socket_timeout=2)
        client.ping()
        return client
    except Exception:  # noqa: BLE001 - Redis 只做锁，连不上退化成无锁
        return None


def fetch_page(key: str, page: int, stat_date: str | None = None,
               range_type: str = DEFAULT_RANGE) -> dict:
    payload: dict = {"key": key, "range": range_type, "page": page}
    if stat_date:
        payload["date"] = stat_date
    response = requests.post(LOWFANS_URL, json=payload, timeout=FETCH_TIMEOUT)
    response.raise_for_status()
    return response.json()


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _row(stat_date: str, range_type: str, raw: dict) -> dict:
    """把上游一条记录摊平成 LowfansArticle 的字段。"""
    return {
        "stat_date": stat_date,
        "range_type": range_type,
        "rank_no": _int(raw.get("rank_no")),
        "art_id": str(raw.get("art_id") or "")[:64],
        "wx_biz": str(raw.get("wx_biz") or "")[:64],
        "wx_name": str(raw.get("wx_name") or "")[:120],
        "wx_type": str(raw.get("wx_type") or "").strip()[:32],
        "avatar": str(raw.get("avatar") or "") or None,
        "title": str(raw.get("title") or ""),
        "art_url": str(raw.get("art_url") or ""),
        "publish_name": str(raw.get("publish_name") or "")[:40] or None,
        "pub_time": str(raw.get("pub_time") or "")[:32] or None,
        "stats_range": str(raw.get("stats_range") or "90d")[:8],
        "account_read_base": _int(raw.get("account_read_base")),
        "account_read_avg": _int(raw.get("account_read_avg")),
        "account_read_median": _int(raw.get("account_read_median")),
        "account_read_max": _int(raw.get("account_read_max")),
        "read_num": _int(raw.get("read_num")),
        "like_num": _int(raw.get("like_num")),
        "look_num": _int(raw.get("look_num")),
        "share_num": _int(raw.get("share_num")),
        "comment_num": _int(raw.get("comment_num")),
        "boost_ratio": _float(raw.get("boost_ratio")),
        "burst_score": _float(raw.get("burst_score")),
    }


def _finish(run_id: int | None, *, status: str, error: str | None = None,
            pages_requested: int = 0, pages_ok: int = 0, calls: int = 0,
            inserted: int = 0, upstream_total: int = 0,
            stat_date: str = "", range_type: str = "") -> dict:
    finished = datetime.now(timezone.utc)
    if run_id is not None:
        try:
            with database.session_scope() as session:
                row = session.get(LowfansSyncRun, run_id)
                if row is not None:
                    row.finished_at = finished
                    row.pages_requested = pages_requested
                    row.pages_ok = pages_ok
                    row.calls = calls
                    row.cost_points = calls * POINTS_PER_CALL
                    row.inserted = inserted
                    row.upstream_total = upstream_total
                    row.status = status
                    row.error = (error or "")[:2000] or None
        except Exception as exc:  # noqa: BLE001 - 审计写失败不影响主流程
            logger.warning("lowfans audit write failed: %s", exc)
    return {"status": status, "pages_requested": pages_requested, "pages_ok": pages_ok,
            "calls": calls, "cost_points": calls * POINTS_PER_CALL,
            "inserted": inserted, "upstream_total": upstream_total,
            "stat_date": stat_date, "range_type": range_type, "error": error or ""}


def _open_run(stat_date: str, range_type: str) -> int | None:
    try:
        with database.session_scope() as session:
            row = LowfansSyncRun(started_at=datetime.now(timezone.utc),
                                 stat_date=stat_date, range_type=range_type)
            session.add(row)
            session.flush()
            return int(row.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("lowfans audit open failed: %s", exc)
        return None


def sync_daily(pages: int | None = None, stat_date: str | None = None,
               range_type: str | None = None) -> dict:
    """拉取 7d 榜单前 N 页并整日替换。失败只记状态，不抛。"""
    started = time.time()
    range_type = range_type or DEFAULT_RANGE
    stat_date = stat_date or yesterday_beijing()
    pages = pages or pages_per_day()
    key = api_key()
    if not key:
        return {"status": "unconfigured", "error": "WXRANK_API_KEY 未配置",
                "stat_date": stat_date, "range_type": range_type}

    client = _redis()
    if client is not None and not client.set(KEY_LOCK, "1", nx=True, ex=900):
        return {"status": "busy", "stat_date": stat_date, "range_type": range_type}

    run_id = _open_run(stat_date, range_type)
    rows: list[dict] = []
    pages_ok = 0
    calls = 0
    errors: list[str] = []
    upstream_total = 0
    try:
        for page in range(1, pages + 1):
            try:
                payload = fetch_page(key, page, stat_date, range_type)
                calls += 1
                code = _int(payload.get("code"))
                if code != 0:
                    errors.append(f"page {page}: code={code} {payload.get('msg') or ''}".strip())
                    if code == 1000:          # 欠费/密钥失效：继续拉只会白扣，直接停
                        break
                    continue
                data = payload.get("data") or {}
                upstream_total = _int(data.get("total")) or upstream_total
                items = data.get("list") or []
                for raw in items:
                    if raw.get("art_id"):
                        rows.append(_row(stat_date, range_type, raw))
                pages_ok += 1
                if not data.get("has_more") or not items:
                    break
            except Exception as exc:  # noqa: BLE001 - 单页失败不影响其它页
                errors.append(f"page {page}: {type(exc).__name__}")
            time.sleep(0.15)                   # 上游 QPS 上限 10/s，留余量

        complete = pages_ok > 0 and not errors

        inserted = 0
        if rows:
            with database.session_scope() as session:
                existing = session.execute(
                    select(func.count()).select_from(LowfansArticle).where(
                        LowfansArticle.stat_date == stat_date,
                        LowfansArticle.range_type == range_type,
                    )).scalar() or 0
                if existing and not complete:
                    # 本次不完整但库里已有整份数据：宁可留旧的，不拿半份覆盖
                    logger.warning("lowfans sync incomplete (%s pages), keep existing %s rows",
                                   pages_ok, existing)
                else:
                    session.execute(delete(LowfansArticle).where(
                        LowfansArticle.stat_date == stat_date,
                        LowfansArticle.range_type == range_type,
                    ))
                    seen: set[str] = set()
                    for item in rows:
                        if item["art_id"] in seen:
                            continue
                        seen.add(item["art_id"])
                        session.add(LowfansArticle(**item))
                        inserted += 1
        else:
            inserted = 0

        if pages_ok == 0:
            status = "failed"
        elif complete:
            status = "ok"
        else:
            status = "partial"
        summary = _finish(run_id, status=status, error="; ".join(errors[:6]) or None,
                          pages_requested=pages, pages_ok=pages_ok, calls=calls,
                          inserted=inserted, upstream_total=upstream_total,
                          stat_date=stat_date, range_type=range_type)
        summary["seconds"] = round(time.time() - started, 1)
        logger.info("lowfans sync: %s", summary)
        return summary
    except Exception as exc:  # noqa: BLE001 - 任何异常都落到审计里
        logger.exception("lowfans sync crashed")
        return _finish(run_id, status="failed", error=f"{type(exc).__name__}: {exc}",
                       pages_requested=pages, pages_ok=pages_ok, calls=calls,
                       stat_date=stat_date, range_type=range_type)
    finally:
        if client is not None:
            client.delete(KEY_LOCK)


def prune(keep_days: int = RETENTION_DAYS) -> int:
    cutoff = (datetime.now(BEIJING) - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    try:
        with database.session_scope() as session:
            result = session.execute(delete(LowfansArticle).where(LowfansArticle.stat_date < cutoff))
            return result.rowcount or 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("lowfans prune failed: %s", exc)
        return 0


def last_run() -> dict:
    try:
        with database.session_scope() as session:
            row = session.execute(
                select(LowfansSyncRun).order_by(LowfansSyncRun.started_at.desc()).limit(1)
            ).scalars().first()
        if row is None:
            return {}
        return {
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "stat_date": row.stat_date, "range_type": row.range_type,
            "pages_requested": row.pages_requested, "pages_ok": row.pages_ok,
            "calls": row.calls, "cost_points": row.cost_points,
            "inserted": row.inserted, "upstream_total": row.upstream_total,
            "status": row.status, "error": row.error or "",
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("lowfans last_run failed: %s", exc)
        return {}


def _task():
    from .celery_app import celery_app

    @celery_app.task(name="lowfans.sync", max_retries=2, default_retry_delay=300)
    def lowfans_sync():
        result = sync_daily()
        if result.get("status") in {"failed", "unconfigured"}:
            raise RuntimeError(f"lowfans sync {result.get('status')}: {result.get('error')}")
        prune()
        return result

    return lowfans_sync


lowfans_sync_task = _task()
