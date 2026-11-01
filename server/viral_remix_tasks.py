"""爆款贴图复刻的 Celery 任务：逐张出图 + 进度 + 按张结算。"""
from __future__ import annotations

import json
import logging
import time

from .celery_app import celery_app
from . import accounts, creator_tools
from . import viral_remix_jobs as jobs


def dispatch(job_id: str) -> str:
    return run.apply_async(args=[job_id], queue=jobs.LANE).id


@celery_app.task(bind=True, name='viral_remix.run', acks_late=True,
                 reject_on_worker_lost=True, soft_time_limit=1800, time_limit=1860)
def run(self, job_id: str):
    job = accounts.claim_job([jobs.LANE], job_id)
    if not job:
        return {'status': 'ignored'}
    payload = json.loads(job['payload_json'] or '{}')
    idea = payload.get('idea') or {}
    session_id = payload.get('session_id') or ''
    started = time.monotonic()
    images: list[dict] = []
    error = ''
    total = int(payload.get('count') or 0)

    try:
        cards, idea, directory = creator_tools.prepare_remix_cards(session_id, idea)
        total = len(cards)
        # 创意展开降级时把原因带到结果里，前端会当成 warning 展示。
        error = idea.get('fallback_note') or ''
        accounts.progress_job(job_id, done=0, total=total, stage='preparing')
        for index, page in enumerate(cards, 1):
            try:
                image = creator_tools.generate_remix_card(idea, page, index, total, directory)
            except Exception as exc:  # noqa: BLE001 - 单张失败不该拖垮整单
                logging.getLogger(__name__).exception('remix card failed: %s', job_id)
                error = str(exc)[:300] or '出图失败'
                break
            images.append(image)
            accounts.progress_job(job_id, done=index, total=total, stage='generating')
    except Exception as exc:  # noqa: BLE001 - 展开创意阶段就失败
        logging.getLogger(__name__).exception('remix job failed: %s', job_id)
        error = str(exc)[:300] or '任务失败'
        accounts.fail_job(job_id, error)
        jobs.settle(job, [], int((time.monotonic() - started) * 1000))
        return {'status': 'failed'}

    elapsed = int((time.monotonic() - started) * 1000)
    if images:
        result = {**images[0], 'images': images,
                  'copy_directions': idea.get('copy_directions', []),
                  'tags': idea.get('tags', {}),
                  'warning': error, 'expected': total}
        accounts.finish_job(job_id, result)
        jobs.settle(job, images, elapsed)
        return {'status': 'succeeded', 'images': len(images), 'expected': total}

    accounts.fail_job(job_id, error or '一张图都没有生成成功')
    jobs.settle(job, [], elapsed)
    return {'status': 'failed'}
