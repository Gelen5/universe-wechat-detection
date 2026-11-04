"""Privacy-minimal behavior metrics, separate from billing truth."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import logging
import uuid
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import MetaData, Table, Column, String, Integer, Index, select, func, case
from . import accounts, database
from .owner_revenue import require_owner
from .auth_rate_limit import client_ip
from .rate_limit import check_behavior_observation

router = APIRouter()
meta = MetaData()
events = Table('behavior_events', meta,
    Column('id', String(32), primary_key=True), Column('visitor', String(64), nullable=False),
    Column('user_id', String(64)), Column('page', String(40), nullable=False),
    Column('event', String(40), nullable=False), Column('seconds', Integer, nullable=False),
    Column('device', String(12), nullable=False), Column('created_at', String(40), nullable=False))
Index('ix_behavior_time', events.c.created_at)
PAGES = {'home','workbench','wechat-plus','one-click-writing','qihaoshou','hotspots','lowfans','image-board','xiaohongshu','tie-tu','viral-remix','article-visual','sticker-extract','xhs-extract','douyin-extract','bookshelf','market','pricing','pay','wallet'}
EVENTS = {'page_view','active_time','open_pricing','choose_starter','choose_pro','choose_master','checkout_submit','remix_analyze','remix_generate','remix_save','article_analyze','article_download','sticker_extract','xhs_extract','douyin_extract','plus_send','plus_copy','welcome_browse','auth_login','auth_register'}
class Observation(BaseModel):
    visitor: str = Field(pattern=r'^[a-f0-9]{32}$')
    page: str = Field(max_length=40)
    event: str = Field(max_length=40)
    seconds: int = Field(default=0, ge=0, le=30)
    device: str = Field(pattern=r'^(mobile|desktop)$')

@router.post('/api/behavior', status_code=204)
def observe(payload: Observation, request: Request):
    if payload.page not in PAGES or payload.event not in EVENTS or (payload.event != 'active_time' and payload.seconds):
        raise HTTPException(422, 'invalid observation')
    user = accounts.user_from_request(request)
    if user and (user.get('role') == 'admin' or user.get('impersonation')):
        return
    if not check_behavior_observation(visitor=payload.visitor, ip=client_ip(request)).allowed:
        return
    try:
        with database.ENGINE.begin() as db:
            db.execute(events.insert().values(id=uuid.uuid4().hex, visitor=payload.visitor,
                user_id=(user or {}).get('id'), page=payload.page, event=payload.event,
                seconds=payload.seconds, device=payload.device, created_at=accounts.utc_now()))
    except Exception:
        logging.getLogger(__name__).warning('Behavior observation unavailable')

@router.get('/owner-behavior', include_in_schema=False)
def behavior_page(request: Request):
    require_owner(request)
    return FileResponse(Path(__file__).resolve().parent.parent/'static'/'owner-behavior.html', headers={'Cache-Control':'no-store'})

@router.get('/api/owner-behavior')
def behavior_report(request: Request, days: int = 7):
    require_owner(request)
    if days not in (1,7,30): raise HTTPException(422, 'invalid period')
    since = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    guest = case((events.c.user_id.is_(None), events.c.visitor), else_=None)
    with database.ENGINE.connect() as db:
        summary = db.execute(select(
            func.count(func.distinct(guest)).label('guest_sessions'),
            func.count(func.distinct(events.c.user_id)).label('users'),
            func.sum((events.c.event == 'page_view').cast(Integer)).label('views'))
            .where(events.c.created_at >= since)).mappings().one()
        pages = db.execute(select(events.c.page,
            func.count(func.distinct(events.c.visitor)).label('visitors'),
            func.count(func.distinct(guest)).label('guest_sessions'),
            func.count(func.distinct(events.c.user_id)).label('users'),
            func.sum(events.c.seconds).label('seconds'),
            func.sum((events.c.event == 'page_view').cast(Integer)).label('views'))
            .where(events.c.created_at >= since).group_by(events.c.page).order_by(func.sum(events.c.seconds).desc())).mappings().all()
        actions = db.execute(select(events.c.page, events.c.event, func.count().label('count'),
            func.count(func.distinct(events.c.visitor)).label('visitors'),
            func.count(func.distinct(guest)).label('guest_sessions'),
            func.count(func.distinct(events.c.user_id)).label('users'))
            .where(events.c.created_at >= since, events.c.event.not_in(['active_time','page_view']))
            .group_by(events.c.page,events.c.event).order_by(func.count().desc()).limit(80)).mappings().all()
        earliest = db.execute(select(func.min(events.c.created_at))).scalar()
    return {'days':days,'since':since,'started_at':earliest,'summary':dict(summary), 'pages':[dict(x) for x in pages], 'actions':[dict(x) for x in actions]}
