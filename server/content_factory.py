"""Exclusive content products. All full content is served after authorization."""
from __future__ import annotations

import json
import re
import requests
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, inspect, select, update
from sqlalchemy.exc import IntegrityError

from . import accounts, database
from .models import LowfansArticle
from .content_factory_purchase import (InsufficientPoints, PurchaseError, SoldOut,
                                       content_fingerprint, feedback, jobs, metadata,
                                       products, purchase)

router = APIRouter(prefix="/api/content-factory", tags=["content-factory"])
PUBLIC_COLUMNS = ("id", "status", "product_type", "title", "track", "preview", "price_points",
                  "source_title", "source_url", "source_date", "source_metrics", "published_at", "buyer_id")


def now():
    return datetime.now(timezone.utc).isoformat()


def ready():
    inspector = inspect(database.ENGINE)
    for table in metadata.sorted_tables:
        if not inspector.has_table(table.name):
            raise HTTPException(503, "成品库尚未完成数据库迁移")
        actual = {column["name"] for column in inspector.get_columns(table.name)}
        if not set(table.c.keys()).issubset(actual):
            raise HTTPException(503, "成品库数据库结构不完整")


def admin(request):
    ready()
    return accounts.require_admin(request)


def safe_source_url(url):
    try:
        parsed = urlparse(url or "")
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except ValueError:
        return False


def public(row, user_id=None):
    return {key: row[key] for key in ("id", "status", "product_type", "title", "track", "preview",
            "price_points", "source_title", "source_url", "source_date", "source_metrics", "published_at")} | {
        "owned": bool(user_id and row["buyer_id"] == user_id)}


class Draft(BaseModel):
    source_row_id: int
    product_type: str = Field(pattern="^(article|image)$")
    title: str = Field(min_length=1, max_length=240)
    track: str = Field(default="", max_length=80)
    preview: str = Field(default="", max_length=1000)
    content: str = Field(default="", max_length=60000)
    price_points: int = Field(ge=1, le=100000)


class Feedback(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class Generate(BaseModel):
    angle: str = Field(min_length=1, max_length=2000)


class StageOpportunity(BaseModel):
    product_type: str = Field(pattern='^(article|image)$')
    angle: str = Field(min_length=1, max_length=500)


class TitlePlan(BaseModel):
    main_title: str = Field(min_length=1, max_length=120)
    alternative_titles: list[str] = Field(max_length=3)
    strategy: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=1, max_length=1000)
    image_text: str | None = Field(default=None, max_length=300)
    caption: str | None = Field(default=None, max_length=3000)
    tags: list[str] | None = Field(default=None, max_length=5)


class AutomationLimits(BaseModel):
    daily_budget_micros: int = Field(ge=0, le=1_000_000_000)
    title_call_bound_micros: int = Field(default=0, ge=0, le=1_000_000_000)
    article_call_bound_micros: int = Field(default=0, ge=0, le=1_000_000_000)
    image_call_bound_micros: int = Field(default=0, ge=0, le=1_000_000_000)
    vision_call_bound_micros: int = Field(default=0, ge=0, le=1_000_000_000)
    detector_call_bound_micros: int = Field(default=0, ge=0, le=1_000_000_000)
    cost_bound_verified: bool = False
    article_limit: int = Field(ge=0, le=100)
    image_limit: int = Field(ge=0, le=100)
    minimum_score: int = Field(default=70, ge=0, le=100)
    tracks: list[str] = Field(max_length=20)


class ProductionMode(BaseModel):
    articles: bool = False
    images: bool = False


class PublishMode(BaseModel):
    articles: bool = False
    images: bool = False


class ScheduleMode(BaseModel):
    enabled: bool = False


@router.get('/admin/opportunities')
def opportunities(request: Request):
    admin(request)
    from .content_factory_opportunities import build_candidates, cluster_candidates
    with database.session_scope() as session:
        return cluster_candidates(build_candidates(session))


@router.get('/admin/opportunities/topics')
def opportunity_topics(request: Request, title: str, track: str = ''):
    admin(request)
    from .content_factory_opportunities import match_topics
    if len(title) > 240 or len(track) > 80:
        raise HTTPException(400, '查询内容过长')
    return match_topics(title, track)


@router.get('/admin/opportunities/images')
def opportunity_images(request: Request):
    admin(request)
    from .content_factory_opportunities import classify_image_evidence
    with database.session_scope() as session:
        return classify_image_evidence(session)


@router.get('/admin/opportunities/hotspots')
def opportunity_hotspots(request: Request, title: str):
    admin(request)
    if len(title) > 240:
        raise HTTPException(400, '查询内容过长')
    from .content_factory_opportunities import find_hotspots
    with database.session_scope() as session:
        return find_hotspots(session, title)


def v3_ready():
    from .content_factory_v3_store import metadata as v3_metadata
    inspector = inspect(database.ENGINE)
    for table in v3_metadata.sorted_tables:
        if not inspector.has_table(table.name):
            raise HTTPException(503, '内容工厂自动化表尚未迁移')
        actual = {column["name"] for column in inspector.get_columns(table.name)}
        if not set(table.c.keys()).issubset(actual):
            raise HTTPException(503, '内容工厂自动化表结构不完整，请执行迁移')


@router.get('/admin/automation')
def automation_status(request: Request):
    admin(request)
    v3_ready()
    from .content_factory_v3_store import get_settings
    with database.ENGINE.connect() as connection:
        return get_settings(connection)


@router.put('/admin/automation/limits')
def automation_limits(payload: AutomationLimits, request: Request):
    admin(request)
    v3_ready()
    from .content_factory_v3_store import settings, ensure_settings, get_settings, utc_now
    tracks = list(dict.fromkeys(value.strip() for value in payload.tracks))
    if any(not value or len(value) > 80 for value in tracks):
        raise HTTPException(400, '赛道名称不能为空或超过80字')
    with database.ENGINE.begin() as connection:
        ensure_settings(connection)
        connection.execute(update(settings).where(settings.c.id == 1).values(
            daily_budget_micros=payload.daily_budget_micros, article_limit=payload.article_limit,
            title_call_bound_micros=payload.title_call_bound_micros, cost_bound_verified=payload.cost_bound_verified,
            article_call_bound_micros=payload.article_call_bound_micros, image_call_bound_micros=payload.image_call_bound_micros,
            vision_call_bound_micros=payload.vision_call_bound_micros,
            detector_call_bound_micros=payload.detector_call_bound_micros,
            image_limit=payload.image_limit, minimum_score=payload.minimum_score,
            tracks_json=json.dumps(tracks, ensure_ascii=False), updated_at=utc_now()))
        return get_settings(connection)


@router.post('/admin/automation/emergency-stop')
def automation_emergency_stop(request: Request):
    admin(request)
    v3_ready()
    from .content_factory_v3_store import emergency_stop_all
    with database.ENGINE.begin() as connection:
        emergency_stop_all(connection)
    return {'stopped': True}


@router.post('/admin/automation/enable-title-planning')
def enable_title_planning(request: Request):
    """Enable only bounded title calls; does not schedule or publish products."""
    admin(request)
    v3_ready()
    from .content_factory_v3_store import settings, ensure_settings, utc_now
    with database.ENGINE.begin() as connection:
        ensure_settings(connection)
        control = connection.execute(select(settings).where(settings.c.id == 1).with_for_update()).mappings().one()
        if (not control['cost_bound_verified'] or control['title_call_bound_micros'] <= 0 or
                control['daily_budget_micros'] < control['title_call_bound_micros']):
            raise HTTPException(409, '请先配置并核实标题调用费用上限及每日预算')
        connection.execute(update(settings).where(settings.c.id == 1).values(
            emergency_stop=False, automatic_selection=True, updated_at=utc_now()))
    return {'title_planning_enabled': True, 'automatic_production_enabled': False}


@router.post('/admin/automation/enable-production')
def enable_production(payload: ProductionMode, request: Request):
    """Enable controlled draft production only; automatic publishing is separate."""
    admin(request)
    v3_ready()
    from .content_factory_v3_store import settings, ensure_settings, utc_now
    with database.ENGINE.begin() as connection:
        ensure_settings(connection)
        control = connection.execute(select(settings).where(settings.c.id == 1).with_for_update()).mappings().one()
        if control['emergency_stop'] or not control['automatic_selection'] or not control['cost_bound_verified']:
            raise HTTPException(409, '请先启用标题规划并核实预算')
        if not json.loads(control['tracks_json']):
            raise HTTPException(409, '请先选择赛道')
        for enabled, kind in ((payload.articles, 'article'), (payload.images, 'image')):
            if enabled and (control[kind + '_limit'] <= 0 or control[kind + '_call_bound_micros'] <= 0 or
                            control[kind + '_call_bound_micros'] > control['daily_budget_micros']):
                raise HTTPException(409, '请先配置生产数量和费用上限')
        if payload.articles and (control['detector_call_bound_micros'] <= 0 or
                control['article_call_bound_micros'] + control['detector_call_bound_micros'] > control['daily_budget_micros']):
            raise HTTPException(409, '请先配置朱雀检测费用上限')
        if payload.images and (control['vision_call_bound_micros'] <= 0 or
                control['image_call_bound_micros'] + control['vision_call_bound_micros'] > control['daily_budget_micros']):
            raise HTTPException(409, '请先配置图片视觉复核费用上限')
        connection.execute(update(settings).where(settings.c.id == 1).values(
            automatic_articles=payload.articles, automatic_images=payload.images,
            automatic_article_publish=control['automatic_article_publish'] and payload.articles,
            automatic_image_publish=control['automatic_image_publish'] and payload.images,
            updated_at=utc_now()))
    return {'articles': payload.articles, 'images': payload.images, 'automatic_publish': False}


@router.post('/admin/automation/enable-publishing')
def enable_publishing(payload: PublishMode, request: Request):
    """Enable automatic listing only for an already healthy production lane."""
    admin(request)
    v3_ready()
    from .content_factory_v3_store import settings, ensure_settings, utc_now
    with database.ENGINE.begin() as connection:
        ensure_settings(connection)
        control = connection.execute(select(settings).where(settings.c.id == 1).with_for_update()).mappings().one()
        if payload.articles or payload.images:
            if control['emergency_stop'] or not control['automatic_selection'] or not control['cost_bound_verified']:
                raise HTTPException(409, '请先启用选题规划并核实预算')
        if payload.articles:
            if not control['automatic_articles'] or control['article_limit'] <= 0:
                raise HTTPException(409, '请先启用文章生产')
            if control['detector_call_bound_micros'] <= 0:
                raise HTTPException(409, '文章自动上架必须配置朱雀检测预算')
        if payload.images:
            if not control['automatic_images'] or control['image_limit'] <= 0:
                raise HTTPException(409, '请先启用图片生产')
            if control['vision_call_bound_micros'] <= 0:
                raise HTTPException(409, '图片自动上架必须配置视觉复核预算')
        connection.execute(update(settings).where(settings.c.id == 1).values(
            automatic_article_publish=payload.articles,
            automatic_image_publish=payload.images, updated_at=utc_now()))
    return {'automatic_article_publish': payload.articles,
            'automatic_image_publish': payload.images}


@router.put('/admin/automation/schedule')
def set_automation_schedule(payload: ScheduleMode, request: Request):
    admin(request)
    v3_ready()
    from .content_factory_v3_store import settings, ensure_settings, utc_now
    with database.ENGINE.begin() as connection:
        ensure_settings(connection)
        control = connection.execute(select(settings).where(settings.c.id == 1).with_for_update()).mappings().one()
        if payload.enabled and (control['emergency_stop'] or not control['automatic_selection'] or
                not control['cost_bound_verified'] or not (control['automatic_articles'] or control['automatic_images'])):
            raise HTTPException(409, '请先配置预算并启用草稿生产')
        connection.execute(update(settings).where(settings.c.id == 1).values(
            scheduled_selection=payload.enabled, updated_at=utc_now()))
    return {'scheduled_selection': payload.enabled,
            'automatic_article_publish': control['automatic_article_publish'],
            'automatic_image_publish': control['automatic_image_publish']}


@router.get('/admin/automation/runs')
def automation_runs(request: Request):
    admin(request)
    v3_ready()
    from .content_factory_v3_store import runs
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(runs).order_by(runs.c.created_at.desc()).limit(100)).mappings().all()
    return [dict(row) for row in rows]


@router.get('/admin/automation/metrics')
def automation_metrics(request: Request):
    admin(request)
    v3_ready()
    from zoneinfo import ZoneInfo
    from .content_factory_v3_store import budget_reservations, detections, quality_reports, runs
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    with database.ENGINE.connect() as connection:
        run_rows = connection.execute(select(runs).where(
            (runs.c.selection_day == day) | (runs.c.production_day == day))).mappings().all()
        quality_rows = connection.execute(select(quality_reports.c.status).join(
            runs, runs.c.id == quality_reports.c.run_id).where(runs.c.production_day == day)).scalars().all()
        detector_rows = connection.execute(select(detections.c.status, detections.c.human_ratio).join(
            runs, runs.c.id == detections.c.run_id).where(runs.c.production_day == day)).mappings().all()
        spent = connection.execute(select(func.coalesce(func.sum(budget_reservations.c.amount_micros), 0))
                                   .where(budget_reservations.c.day == day)).scalar_one()
    product_ids = [row['product_id'] for row in run_rows if row['product_id']]
    with database.ENGINE.connect() as connection:
        sold = 0
        points = 0
        if product_ids:
            sold_rows = connection.execute(select(products.c.price_points).where(
                products.c.id.in_(product_ids), products.c.status == 'sold')).scalars().all()
            sold = len(sold_rows)
            points = sum(sold_rows)
    detector_passed = 0
    for row in detector_rows:
        try:
            ratio = float(row['human_ratio'])
        except (TypeError, ValueError):
            continue
        if row['status'] == 'success' and 0.8 <= ratio <= 1:
            detector_passed += 1
    generated = [row for row in run_rows if row['production_day'] == day and row['product_id']]
    return {
        'day': day,
        'candidates': len({row['id'] for row in run_rows if row['selection_day'] == day}),
        'articles_generated': sum(1 for row in generated if row['product_type'] == 'article'),
        'images_generated': sum(1 for row in generated if row['product_type'] == 'image'),
        'quality_passed': sum(1 for status in quality_rows if status == 'eligible'),
        'detector_passed': detector_passed,
        'auto_published': sum(1 for row in run_rows if row['status'] == 'published'),
        'held': sum(1 for row in run_rows if row['status'] == 'held'),
        'failed': sum(1 for row in run_rows if row['status'] in ('held', 'failed')
                      and row['error'] in ('production_failed', 'title_generation_failed',
                                           'invalid_evidence', 'invalid_run_data')),
        'cost_micros': int(spent or 0),
        'sold_products': sold,
        'points_revenue': points,
    }


@router.get('/admin/automation/exceptions')
def automation_exceptions(request: Request):
    admin(request)
    v3_ready()
    from .content_factory_v3_store import runs
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(runs).where(runs.c.status.in_(['held', 'failed']))
                                  .order_by(runs.c.updated_at.desc()).limit(100)).mappings().all()
    return [dict(row) for row in rows]


@router.get('/admin/automation/runs/{run_id}/detections')
def automation_detections(run_id: str, request: Request):
    admin(request)
    v3_ready()
    from .content_factory_v3_store import detections
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(detections).where(detections.c.run_id == run_id)
                                  .order_by(detections.c.created_at)).mappings().all()
    return [dict(row) for row in rows]


@router.post('/admin/automation/runs/{run_id}/generate-titles')
def automation_generate_titles(run_id: str, request: Request):
    admin(request)
    v3_ready()
    from zoneinfo import ZoneInfo
    from .content_factory_v3_store import queue_title_plan
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    try:
        with database.ENGINE.begin() as connection:
            result = queue_title_plan(connection, run_id=run_id, day=day)
    except ValueError as exc:
        raise HTTPException(409, '任务未准备好、自动化已停止或预算不足') from exc
    if result['existing']:
        return result
    try:
        from .content_factory_v3_tasks import generate_titles
        generate_titles.apply_async(
            args=[run_id], queue='text',
            task_id=f'factory-v3-title-{run_id}-{result["attempt"]}',
        )
    except Exception as exc:
        # Publishing to the broker can be ambiguous; retain the reservation and
        # queued state for an operator to inspect rather than retrying blindly.
        raise HTTPException(503, '任务提交状态不确定，预算已保留，请检查任务') from exc
    return result


@router.post('/admin/automation/runs/{run_id}/produce')
def automation_produce(run_id: str, request: Request):
    admin(request)
    v3_ready()
    from zoneinfo import ZoneInfo
    from .content_factory_v3_store import queue_production
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    try:
        with database.ENGINE.begin() as connection:
            result = queue_production(connection, run_id=run_id, day=day)
    except ValueError as exc:
        raise HTTPException(409, '任务未准备好、来源过期、赛道未开启或预算不足') from exc
    if result['existing']:
        return result
    try:
        from .content_factory_v3_store import runs
        from .content_factory_v3_tasks import produce_draft
        with database.ENGINE.connect() as connection:
            kind = connection.execute(select(runs.c.product_type).where(runs.c.id == run_id)).scalar_one()
        produce_draft.apply_async(
            args=[run_id], queue='image' if kind == 'image' else 'text',
            task_id=f'factory-v3-produce-{run_id}-{result["attempt"]}',
        )
    except Exception as exc:
        raise HTTPException(503, '任务提交状态不确定，预算已保留，请检查任务') from exc
    return result


@router.post('/admin/automation/runs/{run_id}/retry')
def automation_retry(run_id: str, request: Request):
    admin(request)
    v3_ready()
    from zoneinfo import ZoneInfo
    from .content_factory_v3_store import queue_production, queue_title_plan, retry_run
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    try:
        with database.ENGINE.begin() as connection:
            reset = retry_run(connection, run_id=run_id)
            if reset['status'] == 'candidate':
                result = queue_title_plan(connection, run_id=run_id, day=day)
                task_name = 'titles'
            else:
                result = queue_production(connection, run_id=run_id, day=day)
                task_name = 'produce'
    except ValueError as exc:
        raise HTTPException(409, '任务不可重试、自动化已停止或预算不足') from exc
    if result['existing']:
        return {**result, 'attempt': reset['attempt']}
    try:
        from .content_factory_v3_store import runs
        from .content_factory_v3_tasks import generate_titles, produce_draft
        with database.ENGINE.connect() as connection:
            kind = connection.execute(select(runs.c.product_type).where(runs.c.id == run_id)).scalar_one()
        if task_name == 'titles':
            generate_titles.apply_async(
                args=[run_id], queue='text',
                task_id=f'factory-v3-title-{run_id}-{reset["attempt"]}',
            )
        else:
            produce_draft.apply_async(
                args=[run_id], queue='image' if kind == 'image' else 'text',
                task_id=f'factory-v3-produce-{run_id}-{reset["attempt"]}',
            )
    except Exception as exc:
        raise HTTPException(503, '任务提交状态不确定，预算已保留，请检查任务') from exc
    return {**result, 'attempt': reset['attempt']}


@router.post('/admin/automation/runs/{run_id}/dispatch')
def automation_redispatch(run_id: str, request: Request):
    """Re-submit an already queued task after an ambiguous broker response."""
    admin(request)
    v3_ready()
    from .content_factory_v3_store import runs
    with database.ENGINE.connect() as connection:
        run = connection.execute(select(runs.c.status, runs.c.product_type, runs.c.attempt)
                                 .where(runs.c.id == run_id)).mappings().first()
    if not run or run['status'] not in ('title_queued', 'production_queued'):
        raise HTTPException(409, '仅可重新派发仍在排队的任务')
    try:
        if run['status'] == 'title_queued':
            from .content_factory_v3_tasks import generate_titles
            generate_titles.apply_async(
                args=[run_id], queue='text',
                task_id=f'factory-v3-title-{run_id}-{run["attempt"]}',
            )
        else:
            from .content_factory_v3_tasks import produce_draft
            produce_draft.apply_async(
                args=[run_id], queue='image' if run['product_type'] == 'image' else 'text',
                task_id=f'factory-v3-produce-{run_id}-{run["attempt"]}',
            )
    except Exception as exc:
        raise HTTPException(503, '任务提交状态仍不确定，预算已保留，请检查消息队列') from exc
    return {'dispatched': True, 'status': run['status'], 'attempt': run['attempt']}


@router.post('/admin/automation/runs/{run_id}/mark-stale')
def automation_mark_stale(run_id: str, request: Request):
    """Move an overdue task to manual review without repeating paid work."""
    admin(request)
    v3_ready()
    from .content_factory_v3_store import mark_stale_run
    try:
        with database.ENGINE.begin() as connection:
            return mark_stale_run(connection, run_id=run_id)
    except ValueError as exc:
        raise HTTPException(409, '任务未超时、状态已变化或不可标记异常') from exc


@router.put('/admin/automation/runs/{run_id}/titles')
def save_title_plan(run_id: str, payload: TitlePlan, request: Request):
    admin(request)
    v3_ready()
    from .content_factory_titles import validate_titles
    from .content_factory_v3_store import runs, utc_now
    with database.ENGINE.begin() as connection:
        run = connection.execute(select(runs).where(runs.c.id == run_id).with_for_update()).mappings().first()
        if not run:
            raise HTTPException(404, '任务不存在')
        if run['status'] not in ('candidate', 'title_ready'):
            raise HTTPException(409, '任务状态不允许修改标题')
        try:
            evidence = json.loads(run['evidence_json'])
            source_title = (evidence.get('source') or {}).get('title') or ''
            plan = validate_titles(run['product_type'], payload.model_dump(), source_titles=[source_title])
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(400, '标题方案不完整或相似度过高') from exc
        connection.execute(update(runs).where(runs.c.id == run_id, runs.c.status.in_(['candidate', 'title_ready'])).values(
            titles_json=json.dumps(plan, ensure_ascii=False), status='title_ready', updated_at=utc_now()))
    return {'status': 'title_ready'}


@router.post('/admin/opportunities/{source_id}/stage')
def stage_opportunity(source_id: str, payload: StageOpportunity, request: Request):
    admin(request)
    v3_ready()
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from .content_factory_opportunities import build_candidates, classify_image_evidence, match_topics
    from .content_factory_v3_store import stage_candidate
    with database.session_scope() as session:
        if payload.product_type == 'article':
            candidates = build_candidates(session, limit=200)
            candidate = next((item for item in candidates if item['source']['id'] == source_id), None)
        else:
            images = classify_image_evidence(session, limit=200)
            image = next((item for item in images if item['id'] == source_id and
                          item['classification'] == 'verified_lowfans_image'), None)
            candidate = None
            if image and image['title'] and safe_source_url(image['url']):
                try:
                    observed = datetime.fromisoformat(image['observed_at']).replace(tzinfo=timezone.utc)
                    recent = timedelta(0) <= datetime.now(timezone.utc) - observed <= timedelta(days=7)
                except (ValueError, TypeError):
                    recent = False
                if recent:
                    candidate = {'track': image['track'], 'topic': image['title'], 'source': {
                        'id': image['id'], 'title': image['title'], 'url': image['url'],
                        'observed_at': image['observed_at'], 'read_num': image['read_num'],
                        'lowfans_observation': image['lowfans_observation']},
                        'limitations': ['需核验来源内容及素材授权']}
    if not candidate:
        raise HTTPException(400, '未找到满足条件的近期来源')
    candidate['topic_matches'] = match_topics(candidate.get('topic', ''), candidate.get('track', ''))
    day = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    from .content_factory_v3_store import stage_candidate
    with database.ENGINE.begin() as connection:
        return stage_candidate(connection, day=day, product_type=payload.product_type,
                               candidate=candidate, angle=payload.angle)


@router.post("/admin/products/{product_id}/generate")
def generate_product(product_id: str, payload: Generate, request: Request):
    admin(request)
    ident = uuid.uuid4().hex
    with database.ENGINE.begin() as connection:
        row = connection.execute(select(products).where(products.c.id == product_id).with_for_update()).mappings().first()
        if not row or row["status"] != "draft" or row["product_type"] != "article":
            raise HTTPException(409, "仅支持生成文章草稿")
        if connection.execute(select(jobs.c.id).where(jobs.c.product_id == product_id,
                jobs.c.status.in_(["queued", "running"]))).first():
            raise HTTPException(409, "已有生成任务")
        connection.execute(jobs.insert().values(id=ident, product_id=product_id, angle=payload.angle,
                                                status="queued", created_at=now()))
    try:
        from .content_factory_tasks import generate_article
        generate_article.apply_async(args=[ident], queue="chat")
    except Exception as exc:
        with database.ENGINE.begin() as connection:
            connection.execute(update(jobs).where(jobs.c.id == ident).values(status="failed", error="任务提交失败"))
        raise HTTPException(503, "生成任务提交失败，请重试") from exc
    return {"job_id": ident}


@router.get("/admin/jobs/{job_id}")
def job_status(job_id: str, request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        row = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
    if not row:
        raise HTTPException(404, "任务不存在")
    return dict(row)


@router.get("/sources")
def sources(request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(LowfansArticle).order_by(
            LowfansArticle.stat_date.desc(), LowfansArticle.rank_no).limit(200)).mappings().all()
    return [{"id": r["id"], "title": r["title"], "url": r["art_url"], "date": r["stat_date"],
             "read_num": r["read_num"], "boost_ratio": r["boost_ratio"]} for r in rows
            if r["art_id"] and r["title"] and safe_source_url(r["art_url"])]


@router.post("/admin/products")
def create_product(payload: Draft, request: Request):
    admin(request)
    with database.ENGINE.begin() as connection:
        source = connection.execute(select(LowfansArticle.__table__).where(
            LowfansArticle.id == payload.source_row_id)).mappings().first()
        if not source or not source["art_id"] or not source["title"] or not safe_source_url(source["art_url"]):
            raise HTTPException(400, "来源缺少有效链接或标题")
        ident = uuid.uuid4().hex
        connection.execute(products.insert().values(
            id=ident, status="draft", product_type=payload.product_type, title=payload.title,
            track=payload.track, preview=payload.preview, content=payload.content, price_points=payload.price_points,
            source_id=source["art_id"], source_title=source["title"], source_url=source["art_url"],
            source_date=source["stat_date"], source_metrics=json.dumps({"read_num": source["read_num"],
                "boost_ratio": source["boost_ratio"], "account_read_base": source["account_read_base"]}), created_at=now()))
    return {"id": ident}


@router.get("/admin/products")
def admin_products(request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(*(products.c[key] for key in PUBLIC_COLUMNS), products.c.content,
            products.c.image_data.is_not(None).label("has_image"))
            .order_by(products.c.created_at.desc()).limit(200)).mappings().all()
    return [{**public(r), "content": r["content"], "has_image": r["has_image"]} for r in rows]


@router.get("/admin/feedback")
def admin_feedback(request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(feedback).order_by(feedback.c.created_at.desc()).limit(200)).mappings().all()
    return [dict(row) for row in rows]


@router.put("/admin/products/{product_id}")
def edit_product(product_id: str, payload: Draft, request: Request):
    admin(request)
    with database.ENGINE.begin() as connection:
        result = connection.execute(update(products).where(products.c.id == product_id,
            products.c.status == "draft").values(title=payload.title, track=payload.track,
            preview=payload.preview, content=payload.content, price_points=payload.price_points))
        if not result.rowcount:
            raise HTTPException(409, "只能修改草稿")
    return {"ok": True}


@router.put("/admin/products/{product_id}/image")
async def upload_image(product_id: str, request: Request):
    admin(request)
    data = await request.body()
    if not 0 < len(data) <= 8 * 1024 * 1024:
        raise HTTPException(400, "图片不能超过 8 MB")
    import io
    from PIL import Image, ImageFilter, ImageOps
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 24_000_000:
                raise ValueError("image dimensions exceed limit")
            image.verify()
            fmt = image.format
    except Exception as exc:
        raise HTTPException(400, "无效图片") from exc
    if fmt not in {"PNG", "JPEG", "WEBP"}:
        raise HTTPException(400, "仅支持 PNG、JPEG、WebP")
    try:
        with Image.open(io.BytesIO(data)) as image:
            preview = ImageOps.exif_transpose(image).convert("RGB")
            preview.thumbnail((160, 160))
            preview = preview.filter(ImageFilter.GaussianBlur(radius=8))
            buffer = io.BytesIO()
            preview.save(buffer, format="JPEG", quality=65)
    except Exception as exc:
        raise HTTPException(400, "图片无法生成预览") from exc
    with database.ENGINE.begin() as connection:
        changed = connection.execute(update(products).where(products.c.id == product_id,
            products.c.status == "draft", products.c.product_type == "image").values(
                image_data=data, image_type={"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt],
                preview_image=buffer.getvalue()))
        if not changed.rowcount:
            raise HTTPException(409, "只能为图片草稿上传图片")
    return {"ok": True}


@router.get("/admin/products/{product_id}/image")
def admin_image(product_id: str, request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        row = connection.execute(select(products.c.image_data, products.c.image_type).where(
            products.c.id == product_id)).first()
    if not row or not row.image_data:
        raise HTTPException(404, "图片不存在")
    return Response(row.image_data, media_type=row.image_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/admin/products/{product_id}/publish")
def publish(product_id: str, request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        candidate = connection.execute(select(products.c.content, products.c.product_type).where(products.c.id == product_id)).mappings().first()
    if not candidate:
        raise HTTPException(404, '商品不存在')
    if candidate and candidate['product_type'] == 'article':
        article = candidate['content'].strip()
        count = len(re.sub(r'\s+', '', article))
        if not 1000 <= count <= 1200:
            raise HTTPException(400, f'文章字数须为1000至1200字（不计空白），当前 {count} 字')
        from .content_factory_detector import detect
        result = detect(article)
        if result.get('error') == 'not_configured':
            raise HTTPException(503, '朱雀检测未配置，暂不能上架文章')
        if result.get('status') != 'success':
            raise HTTPException(503, '朱雀检测失败，请稍后重试')
        human = result['human_ratio']
        if human < 0.8:
            raise HTTPException(400, f'朱雀人工内容占比 {human * 100:.1f}%，需达到80%')
    try:
        with database.ENGINE.begin() as connection:
            row = connection.execute(select(products).where(products.c.id == product_id).with_for_update()).mappings().first()
            if not row or row["status"] != "draft" or not row["source_url"] or not row["source_title"]:
                raise HTTPException(409, "商品或来源不完整")
            if row['product_type'] != candidate['product_type'] or (row['product_type'] == 'article' and row['content'].strip() != article):
                raise HTTPException(409, '文章已修改，请重新检测')
            if connection.execute(select(jobs.c.id).where(jobs.c.product_id == product_id,
                    jobs.c.status.in_(["queued", "running"]))).first():
                raise HTTPException(409, "生成任务尚未完成")
            if not row["content"].strip() or (row["product_type"] == "image" and not row["image_data"]):
                raise HTTPException(400, "请先填写完整内容并检查图片")
            fingerprint = content_fingerprint(row["product_type"], row["content"], row["image_data"])
            connection.execute(update(products).where(products.c.id == product_id).values(
                status="published", published_at=now(), content_fingerprint=fingerprint))
    except IntegrityError as exc:
        raise HTTPException(409, "相同成品已上架或售出，不能重复上架") from exc
    return {"ok": True}


@router.post("/admin/products/{product_id}/hide")
def hide(product_id: str, request: Request):
    admin(request)
    with database.ENGINE.begin() as connection:
        result = connection.execute(update(products).where(products.c.id == product_id,
            products.c.status == "published").values(status="hidden"))
        if not result.rowcount:
            raise HTTPException(409, "仅可下架未售出的商品")
    return {"ok": True}


@router.get("/products")
def list_products(request: Request):
    ready()
    user = getattr(request.state, "user", None)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(*(products.c[key] for key in PUBLIC_COLUMNS)).where(products.c.status.in_(["published", "sold"]))
            .order_by(products.c.published_at.desc()).limit(200)).mappings().all()
    return [public(r, user["id"] if user else None) for r in rows]


@router.get("/products/{product_id}/preview-image")
def preview_image(product_id: str):
    ready()
    with database.ENGINE.connect() as connection:
        data = connection.execute(select(products.c.preview_image).where(
            products.c.id == product_id, products.c.status.in_(["published", "sold"]))).scalar_one_or_none()
    if not data:
        raise HTTPException(404, "预览不存在")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.get("/my-purchases")
def mine(request: Request):
    ready()
    user = accounts.require_user(request)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(*(products.c[key] for key in PUBLIC_COLUMNS)).where(products.c.buyer_id == user["id"])).mappings().all()
    return [public(r, user["id"]) for r in rows]


@router.post("/products/{product_id}/purchase")
def buy(product_id: str, request: Request):
    ready()
    user = accounts.require_user(request)
    try:
        return purchase(database.ENGINE, product_id, user["id"])
    except InsufficientPoints as exc:
        raise HTTPException(402, str(exc)) from exc
    except (SoldOut, PurchaseError) as exc:
        raise HTTPException(409, str(exc)) from exc


def owned(product_id, request, *, include_image=False):
    ready()
    user = accounts.require_user(request)
    with database.ENGINE.connect() as connection:
        image_column = products.c.image_data if include_image else products.c.image_data.is_not(None).label("has_image")
        row = connection.execute(select(products.c.title, products.c.content, products.c.image_type, image_column).where(products.c.id == product_id,
            products.c.buyer_id == user["id"])).mappings().first()
    if not row:
        raise HTTPException(404, "未找到已购买内容")
    return row, user


@router.get("/products/{product_id}/content")
def content(product_id: str, request: Request, response: Response):
    row, _ = owned(product_id, request)
    response.headers["Cache-Control"] = "private, no-store"
    result = {"title": row["title"], "content": row["content"], "has_image": row["has_image"]}
    from .content_factory_v3_store import product_details
    if inspect(database.ENGINE).has_table(product_details.name):
        with database.ENGINE.connect() as connection:
            details = connection.execute(select(product_details.c.details_json).where(
                product_details.c.product_id == product_id)).scalar_one_or_none()
        if details:
            result['details'] = json.loads(details)
    return result


@router.get("/products/{product_id}/image")
def image(product_id: str, request: Request):
    row, _ = owned(product_id, request, include_image=True)
    if not row["image_data"]:
        raise HTTPException(404, "图片不存在")
    return Response(row["image_data"], media_type=row["image_type"], headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/products/{product_id}/feedback")
def submit_feedback(product_id: str, payload: Feedback, request: Request):
    _, user = owned(product_id, request)
    with database.ENGINE.begin() as connection:
        connection.execute(feedback.insert().values(id=uuid.uuid4().hex, product_id=product_id,
            user_id=user["id"], body=payload.body, created_at=now()))
    return {"ok": True}
