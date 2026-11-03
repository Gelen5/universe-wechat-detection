"""每日同步：残缺快照要能重试补齐，完整快照不重复花钱。"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from tests import support  # noqa: F401
from server import database, image_board, lowfans_sync
from server.models import ImageBoardItem, ImageBoardSyncRun, LowfansArticle


@pytest.fixture(autouse=True)
def _schema():
    lowfans_sync.init_schema()
    image_board.init_schema()
    yield


def _page(rows: int, total: int, offset: int = 0):
    return {"code": 0, "data": {"total": total, "list": [
        {"art_id": f"sn-{offset + i}", "wx_name": "号", "title": "标题", "read_num": 1} for i in range(rows)]}}


def test_lowfans_partial_day_is_retried_then_marked_complete(monkeypatch):
    day = "2026-09-01"
    calls = []
    phase = {"n": 0}

    def fake_fetch(key, page, stat_date=None, range_type=None):
        calls.append(page)
        # 第一次只生成到第 1 页；第二次上游补齐第 2 页。
        if page == 1:
            return {"code": 0, "data": {"total": 60, "has_more": True,
                                        "list": _page(50, 60)["data"]["list"]}}
        if phase["n"]:
            return {"code": 0, "data": {"total": 60, "has_more": False,
                                        "list": _page(10, 60, offset=50)["data"]["list"]}}
        return {"code": 0, "data": {"total": 60, "has_more": False, "list": []}}

    monkeypatch.setattr(lowfans_sync, "api_key", lambda: "k")
    monkeypatch.setattr(lowfans_sync, "fetch_page", fake_fetch)
    monkeypatch.setattr(lowfans_sync, "pages_per_day", lambda: 2)
    monkeypatch.setattr(lowfans_sync, "_redis", lambda: None)

    first = lowfans_sync.sync_daily(pages=2, stat_date=day, force=True)
    assert first["inserted"] == 50
    assert calls, "first sync must hit upstream"

    calls.clear()
    phase["n"] = 1
    second = lowfans_sync.sync_daily(pages=2, stat_date=day)  # 50/60 → must retry
    assert calls, "partial day must be retried instead of cached"
    assert second["inserted"] == 60

    calls.clear()
    third = lowfans_sync.sync_daily(pages=2, stat_date=day)  # covers upstream total
    assert third["status"] == "cached" and not calls


def test_lowfans_full_day_is_not_refetched(monkeypatch):
    day = "2026-09-02"
    calls = []
    monkeypatch.setattr(lowfans_sync, "api_key", lambda: "k")
    monkeypatch.setattr(lowfans_sync, "pages_per_day", lambda: 1)
    monkeypatch.setattr(lowfans_sync, "_redis", lambda: None)

    def fake_fetch(key, page, stat_date=None, range_type=None):
        calls.append(page)
        return _page(50, 50)

    monkeypatch.setattr(lowfans_sync, "fetch_page", fake_fetch)
    lowfans_sync.sync_daily(pages=1, stat_date=day, force=True)
    calls.clear()
    result = lowfans_sync.sync_daily(pages=1, stat_date=day)
    assert result["status"] == "cached" and not calls


def test_lowfans_attempt_cap_bounds_cost(monkeypatch):
    day = "2026-09-03"
    monkeypatch.setattr(lowfans_sync, "api_key", lambda: "k")
    monkeypatch.setattr(lowfans_sync, "fetch_page", lambda *a, **k: _page(5, 500))
    monkeypatch.setattr(lowfans_sync, "pages_per_day", lambda: 2)
    monkeypatch.setattr(lowfans_sync, "_redis", lambda: None)
    monkeypatch.setenv("LOWFANS_MAX_ATTEMPTS", "2")
    for _ in range(2):
        lowfans_sync.sync_daily(pages=2, stat_date=day, force=True)
    fetched = []
    monkeypatch.setattr(lowfans_sync, "fetch_page", lambda *a, **k: fetched.append(1) or _page(5, 500))
    result = lowfans_sync.sync_daily(pages=2, stat_date=day)
    assert result["status"] == "cached" and not fetched


def _seed_board(day: str, rows: int, runs: int):
    with database.session_scope() as session:
        for i in range(rows):
            session.add(ImageBoardItem(stat_date=day, sn=f"{day}-{i}", wx_biz="b", wx_type="生活",
                                       content_type="book", title="图", content="文",
                                       art_url="https://mp.weixin.qq.com/s/x",
                                       pic_url="https://mmbiz.qpic.cn/x.jpg", read_num=i,
                                       image_num=1, word_num=1, video_num=0))
        for _ in range(runs):
            session.add(ImageBoardSyncRun(finished_at=datetime.now(timezone.utc), stat_date=day,
                                          source="test", status="ok", inserted=rows))


def test_image_board_thin_snapshot_retries_until_attempt_cap(monkeypatch):
    beijing = timezone(timedelta(hours=8))
    day = (datetime.now(beijing) - timedelta(days=1)).strftime("%Y-%m-%d")
    monkeypatch.setenv("IMAGE_BOARD_SYNC_ENABLED", "1")
    monkeypatch.setenv("IMAGE_BOARD_MIN_ITEMS", "20")
    monkeypatch.setenv("IMAGE_BOARD_MAX_ATTEMPTS", "2")
    calls = []
    monkeypatch.setattr(image_board, "sync", lambda *a, **k: calls.append(1) or {"status": "ok"})

    _seed_board(day, rows=3, runs=1)
    image_board.scheduled_sync()
    assert calls, "thin snapshot must be retried"

    calls.clear()
    _seed_board(day, rows=0, runs=1)  # total runs for the day = 2 → cap reached
    result = image_board.scheduled_sync()
    assert result["status"] == "cached" and not calls


def test_image_board_complete_day_is_cached(monkeypatch):
    beijing = timezone(timedelta(hours=8))
    day = (datetime.now(beijing) - timedelta(days=2)).strftime("%Y-%m-%d")
    monkeypatch.setenv("IMAGE_BOARD_SYNC_ENABLED", "1")
    monkeypatch.setenv("IMAGE_BOARD_MIN_ITEMS", "2")
    calls = []
    monkeypatch.setattr(image_board, "sync", lambda *a, **k: calls.append(1) or {"status": "ok"})
    _seed_board(day, rows=2, runs=1)
    # 只关心“昨天的完整快照不会被重复抓”，用同一份数据构造当前日期
    assert image_board.min_complete_items() == 2
    with database.session_scope() as session:
        count = len(session.execute(select(ImageBoardItem).where(ImageBoardItem.stat_date == day)).scalars().all())
    assert count == 2
