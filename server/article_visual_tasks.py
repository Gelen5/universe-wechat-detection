"""Durable article visual planning jobs and idempotent point settlement."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

from . import accounts, article_visual
from .celery_app import celery_app
from .observability import event as log_event

TYPE = 'article_visual.plan'
LANE = 'text'


def public(job):
    result = json.loads(job.get('result_json') or '{}')
    billing = None
    if job.get('usage_id'):
        with accounts._connect() as connection:
            row = connection.execute('SELECT status FROM usage_records WHERE request_id=?', (job['usage_id'],)).fetchone()
            billing = row['status'] if row else None
    return {'id': job['id'], 'status': job['status'], 'billing_status': billing, 'progress': result.get('progress') or {},
            'result': result.get('plan_result'), 'error': job.get('error') or '',
            'created_at': job.get('created_at'), 'resume_available': has_checkpoint(job)}


def has_checkpoint(job):
    return (job.get('status') == 'failed'
            and (article_visual._job_dir(job['id']) / 'plan-checkpoint.json').is_file())


def dispatch(job_id):
    return run.apply_async(args=[job_id], queue=LANE)


@celery_app.task(bind=True, name='article_visual.plan', acks_late=True,
                 reject_on_worker_lost=True, soft_time_limit=720, time_limit=750)
def run(self, job_id):
    existing = accounts.job(job_id)
    if not existing or existing['type'] != TYPE:
        return {'status': 'ignored'}
    if existing['status'] == 'succeeded':
        if existing.get('usage_id'):
            accounts.settle_usage(existing['usage_id'], 200, 0)
        return {'status': 'succeeded'}
    job = accounts.claim_job([LANE], job_id)
    if not job:
        return {'status': 'ignored'}
    started = time.monotonic()
    def progress(stage, current=0, total=0):
        accounts.progress_job(job_id, stage=stage, current=current, total=total)
    try:
        payload = json.loads(job.get('payload_json') or '{}')
        options = {'progress': progress, 'job_id': job_id}
        if payload.get('resume_task_id'):
            options['resume_id'] = payload['resume_task_id']
        if payload.get('preflight_id'):
            options['preflight_id'] = payload['preflight_id']
        if payload.get('source_text'):
            options['source_text'] = payload['source_text']
            options['source_title'] = payload.get('source_title', '')
        result = article_visual.create_plan_for_user(payload['url'], job['user_id'], **options)
    except Exception as exc:
        logging.getLogger(__name__).warning('article_visual task_failed job_id=%s kind=%s', job_id, type(exc).__name__)
        try:
            current = accounts.job(job_id) or {}
            stage = (json.loads(current.get('result_json') or '{}').get('progress') or {}).get('stage') or 'unknown'
        except (TypeError, ValueError):
            stage = 'unknown'
        log_event('article_visual.task_failed', job_id=job_id, stage=stage, error_type=type(exc).__name__)
        detail = getattr(exc, 'detail', None)
        error = str(detail) if isinstance(detail, str) else '拆解服务内部异常，未能完成本次任务。请稍后重试；如反复出现，请联系客服并提供任务编号。'
        accounts.fail_job(job_id, str(error)[:300])
        if job.get('usage_id'):
            accounts.refund_usage(job['usage_id'], 500, int((time.monotonic() - started) * 1000))
        return {'status': 'failed'}
    accounts.finish_job(job_id, {'plan_result': result})
    log_event('article_visual.task_completed', job_id=job_id, directions=len((result.get('plan') or {}).get('alternatives') or []))
    if job.get('usage_id'):
        try:
            accounts.settle_usage(job['usage_id'], 200, int((time.monotonic() - started) * 1000))
        except Exception:
            logging.getLogger(__name__).warning('article_visual settlement_pending job_id=%s', job_id)
    if (result.get('plan') or {}).get('background_status') == 'pending':
        try:
            dispatch_more_directions(job_id)
        except Exception:
            logging.getLogger(__name__).warning('article_visual additional directions dispatch failed job_id=%s', job_id)
            _merge_more_directions(job_id, [], 'unavailable', '后台补充任务提交失败，已有方向可以继续使用。')
    return {'status': 'succeeded'}


def dispatch_more_directions(job_id):
    return more_directions.apply_async(args=[job_id], queue=LANE)


def _merge_more_directions(job_id, additional, status, notice=""):
    # Compare-and-swap protects user choices and images from being overwritten by
    # the background task, including concurrent requests on another process.
    from sqlalchemy import text
    from . import database
    for _ in range(3):
        with database.session_scope() as session:
            row = session.execute(text('SELECT payload FROM article_visual_jobs WHERE id=:id'), {'id': job_id}).fetchone()
            if not row:
                return False
            previous = row[0]
            job = json.loads(previous)
            plan = job.get('plan') or {}
            if plan.get('background_status') != 'pending':
                return False
            plan['alternatives'] = (plan.get('alternatives') or []) + additional[:2]
            plan['background_status'] = status
            plan['background_notice'] = notice[:300]
            updated = json.dumps(job, ensure_ascii=False)
            result = session.execute(text('UPDATE article_visual_jobs SET payload=:new, updated_at=:now WHERE id=:id AND payload=:old'),
                {'new': updated, 'now': accounts.utc_now(), 'id': job_id, 'old': previous})
            if result.rowcount:
                return True
    return False


@celery_app.task(name='article_visual.more_directions', acks_late=True, reject_on_worker_lost=True, soft_time_limit=600, time_limit=630)
def more_directions(job_id):
    try:
        job = article_visual._read_job(job_id)
        plan = job.get('plan') or {}
        if plan.get('background_status') != 'pending':
            return {'status': 'skipped'}
        checkpoint = json.loads((article_visual._job_dir(job_id) / 'plan-checkpoint.json').read_text(encoding='utf-8'))
        if checkpoint.get('user_id') != job.get('user_id') or article_visual.article_digest(checkpoint['article']) != job.get('article_digest'):
            raise ValueError('checkpoint mismatch')
        result = article_visual.build_plan(checkpoint['article'], initial_raw=checkpoint['raw'], trace_id=job_id,
            skip_indices=(int(plan['first_candidate_index']),))
        merged = _merge_more_directions(job_id, result.get('alternatives') or [], 'complete')
        return {'status': 'completed' if merged else 'skipped'}
    except Exception as exc:
        logging.getLogger(__name__).exception('article_visual additional directions failed job_id=%s', job_id)
        detail = str(exc) if isinstance(exc, ValueError) and str(exc).startswith('文章正文已读取，但方案检查未通过：') else ''
        notice = ('其他方向未完成：' + detail[:200]) if detail else '其他方向未完成，可能是复核、模型服务或网络异常，暂无法确定具体原因。已有方向可以继续使用。'
        _merge_more_directions(job_id, [], 'unavailable', notice)
        return {'status': 'unavailable'}


@celery_app.task(name='article_visual.recover')
def recover():
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    orphan_cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with accounts.DB_LOCK, accounts._connect() as connection:
        connection.execute("UPDATE jobs SET status='queued',started_at=NULL WHERE type=? AND status='running' AND started_at<? AND attempts<2", (TYPE, cutoff))
        stale = connection.execute("SELECT id,usage_id FROM jobs WHERE type=? AND status='running' AND started_at<? AND attempts>=2", (TYPE, cutoff)).fetchall()
        queued = connection.execute("SELECT id FROM jobs WHERE type=? AND status='queued'", (TYPE,)).fetchall()
        unsettled = connection.execute("SELECT j.usage_id FROM jobs j JOIN usage_records u ON u.request_id=j.usage_id WHERE j.type=? AND j.status='succeeded' AND u.status='reserved'", (TYPE,)).fetchall()
        unrefunded = connection.execute("SELECT j.usage_id FROM jobs j JOIN usage_records u ON u.request_id=j.usage_id WHERE j.type=? AND j.status IN ('failed','canceled') AND u.status='reserved'", (TYPE,)).fetchall()
        orphans = connection.execute("SELECT u.request_id FROM usage_records u WHERE u.path=? AND u.status='reserved' AND u.created_at<? AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.usage_id=u.request_id)", ('/api/article-visual/tasks/start', orphan_cutoff)).fetchall()
    for row in stale:
        accounts.fail_job(row['id'], '任务中断，请重新拆解；积分已退回')
        current = accounts.job(row['id'])
        if row['usage_id'] and current and current['status'] == 'failed':
            accounts.refund_usage(row['usage_id'], 503, 0)
    for row in queued:
        dispatch(row['id'])
    for row in unsettled:
        accounts.settle_usage(row['usage_id'], 200, 0)
    for row in unrefunded:
        accounts.refund_usage(row['usage_id'], 500, 0)
    for row in orphans:
        accounts.refund_usage(row['request_id'], 503, 0)
    return {'queued': len(queued), 'failed': len(stale), 'settled': len(unsettled), 'refunded': len(unrefunded) + len(orphans)}
