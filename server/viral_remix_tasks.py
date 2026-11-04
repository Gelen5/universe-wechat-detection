"""爆款贴图复刻的 Celery 任务：逐张出图 + 进度 + 按张结算。"""
from __future__ import annotations

import json
import logging
import time

from .celery_app import celery_app
from . import accounts, creator_tools
from . import viral_remix_jobs as jobs
from . import workbench
from .providers import call_context


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
        # 必须先进入 provider_overrides：workbench._setting 只认「请求级覆盖 + 环境变量」，
        # 后台「统一 API 设置」写在 provider_settings 表里。少了这一层，文字模型会退回
        # 默认的 https://api.openai.com/v1（国内直连不通），于是每次都在 135 秒后
        # 报 transport 失败——生图当时根本没被调用到。
        with workbench.provider_overrides():
            cards, idea, directory = creator_tools.prepare_remix_cards(session_id, idea)
        # Keep each completed job in its own persistent directory.  Older jobs
        # retain their original paths and are never moved or overwritten.
        directory = directory.parent / f'remix-{job_id}'
        directory.mkdir(parents=True, exist_ok=True)
        total = len(cards)
        # 创意展开降级时把原因带到结果里，前端会当成 warning 展示。
        error = idea.get('fallback_note') or ''
        accounts.progress_job(job_id, done=0, total=total, stage='preparing')
        for index, page in enumerate(cards, 1):
            try:
                with workbench.provider_overrides(), call_context.bind(job_id=job_id, user_id=job.get("user_id")):
                    image = creator_tools.generate_remix_card(idea, page, index, total, directory)
                    if idea.get('content_ledger') and not idea.get('data_contract'):
                        from . import remix_quality
                        accounts.progress_job(job_id, done=len(images), total=total, stage='validating', images=images)
                        file = directory / f'remix-{index:02d}.jpg'
                        try:
                            report = remix_quality.inspect_image(file, idea, {**page, 'page_index': index})
                            image['acceptance'] = report
                            image['check_passed'] = report['passed']
                            if not report['passed']:
                                image['review_notice'] = '检查发现可能的问题，请核对：' + '；'.join(report['issues'])
                        except Exception:  # 检查服务故障不影响已生成图片交付
                            logging.getLogger(__name__).exception('remix image review failed: %s', job_id)
                            image['review_notice'] = '自动检查暂不可用，请自行核对图片中的文字、数字和关键信息。'
                    else:
                        image['review_notice'] = '请核对图片中的文字、数字和关键信息。'
            except Exception as exc:  # noqa: BLE001 - 单张失败不该拖垮整单
                logging.getLogger(__name__).exception('remix card failed: %s', job_id)
                error = str(exc)[:300] or '出图失败'
                break
            images.append(image)
            accounts.progress_job(job_id, done=index, total=total, stage='generating', images=images)
    except Exception as exc:  # noqa: BLE001 - 展开创意阶段就失败
        logging.getLogger(__name__).exception('remix job failed: %s', job_id)
        error = str(exc)[:300] or '任务失败'
        accounts.fail_job(job_id, error)
        jobs.settle(job, [], int((time.monotonic() - started) * 1000))
        return {'status': 'failed'}

    elapsed = int((time.monotonic() - started) * 1000)
    if images:
        result = {**images[0], 'images': images,
                  'publication': None,
                  'copy_directions': idea.get('copy_directions', []),
                  'tags': idea.get('tags', {}),
                  'warning': error, 'expected': total}
        result['source_fingerprint'] = idea.get('source_fingerprint')
        result['design_style'] = idea.get('design_style') or idea.get('id')
        result['content_type'] = (idea.get('content_ledger') or {}).get('category')
        accounts.finish_job(job_id, result)
        jobs.settle(job, images, elapsed)
        return {'status': 'succeeded', 'images': len(images), 'expected': total}

    accounts.fail_job(job_id, error or '一张图都没有生成成功')
    jobs.settle(job, [], elapsed)
    return {'status': 'failed'}
