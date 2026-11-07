"""爆款贴图复刻的 Celery 任务：逐张出图 + 进度 + 按张结算。"""
from __future__ import annotations

import json
import logging
import re
import time

from .celery_app import celery_app
from . import accounts, creator_tools
from . import viral_remix_jobs as jobs
from . import workbench
from .providers import call_context


def _retry_wrong_language(image, report, idea, page, index, total, directory, job_id, existing_images):
    """Retry once only for an explicit language mismatch; keep the original on any failure."""
    issues = '；'.join(report.get('issues') or [])
    if (report.get('passed') or not re.search(r'英文|英语|英語|english|拉丁字母', issues, re.I)
            or not creator_tools.remix_chinese_text_required(idea, page, index)):
        return image, report, False
    from . import remix_quality
    retry_dir = directory / f'language-retry-{index:02d}'
    retry_dir.mkdir(parents=True, exist_ok=True)
    instruction = ('请保留中文核心问题和完整中文标题、副标题，不要翻译成英文；合同、文件等背景道具不要出现英文或虚构条款。'
                   '保留方案视觉层次与原有事实，不增加事实或数字。')
    try:
        accounts.progress_job(job_id, done=len(existing_images), total=total, stage='repairing', images=existing_images)
        retry = creator_tools.generate_remix_card(idea, {**page, 'repair_instruction': instruction}, index, total, retry_dir)
        retry_file = retry_dir / f'remix-{index:02d}.jpg'
        checked = remix_quality.inspect_image(retry_file, idea, {**page, 'page_index': index})
        if checked['passed']:
            retry_file.replace(directory / f'remix-{index:02d}.jpg')
            retry_case = retry_dir / f'case-{index:02d}.json'
            try:
                if retry_case.exists():
                    retry_case.replace(directory / f'case-{index:02d}.json')
            except OSError:
                logging.getLogger(__name__).exception('remix language repair audit update failed: %s', job_id)
            retry['url'] = image['url']
            return retry, checked, True
    except Exception:
        logging.getLogger(__name__).exception('remix language repair failed: %s', job_id)
    return image, report, True


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
                            image, report, retried = _retry_wrong_language(image, report, idea, page, index, total, directory, job_id, images)
                            image['acceptance'] = report
                            image['check_passed'] = report['passed']
                            if not report['passed']:
                                image['review_notice'] = ('自动修复后仍需核对：' if retried else '检查发现可能的问题，请核对：') + '；'.join(report['issues'])
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


# ---------------------------------------------------------------- 拆解（视觉分析）
def analyze_dispatch(job_id: str) -> str:
    return analyze_job.apply_async(args=[job_id], queue=jobs.ANALYZE_LANE).id


@celery_app.task(bind=True, name='viral_remix.analyze', acks_late=True,
                 reject_on_worker_lost=True, soft_time_limit=300, time_limit=330)
def analyze_job(self, job_id: str):
    """参考图拆解：Redis 取图 → 视觉分析 → 落 session → 结算。

    参考图只经过 Redis（TTL 到期自动消失），不进 jobs.payload_json：
    任务负载里只有一个 token，失败重试也不会把用户原图留在数据库里。
    """
    job = accounts.claim_job([jobs.ANALYZE_LANE], job_id)
    if not job:
        return {'status': 'ignored'}
    payload = json.loads(job['payload_json'] or '{}')
    token = payload.get('token') or ''
    goal = payload.get('goal') or ''
    session_id = payload.get('session_id') or ''
    preserve_person = bool(payload.get('preserve_person'))
    started = time.monotonic()
    from . import remix_reference, remix_contract

    try:
        images = remix_reference.load(token)
        with workbench.provider_overrides(), call_context.bind(job_id=job_id, user_id=job.get('user_id')):
            result = creator_tools.viral_remix_analysis(images, goal, request_id=job_id)
        ledger = remix_contract.build(result, goal, preserve_person)
        result['content_type'] = ledger['category']
        result['source_fingerprint'] = ledger['fingerprint']
        if session_id:
            # 只留归一化后的首图，和旧同步接口保持同样的续作能力，但更小。
            reference = images[0]
            accounts.save_workbench_session(job['user_id'], {
                'id': session_id,
                'conversation_skill': 'viral-remix',
                'result': result,
                'content_ledger': ledger,
                'goal': goal,
                'product_reference': reference if ledger['category'] == 'product' else None,
                'preserve_person': preserve_person,
                'person_reference': reference if preserve_person else None,
            })
        elapsed = int((time.monotonic() - started) * 1000)
        accounts.finish_job(job_id, {'result': result})
        jobs.settle_analyze(job, True, elapsed)
        return {'status': 'succeeded', 'session_id': session_id}
    except Exception as exc:  # noqa: BLE001 - 失败必须退款并留下可读原因
        logging.getLogger(__name__).exception('remix analysis failed: %s', job_id)
        accounts.fail_job(job_id, str(exc)[:300] or '拆解失败')
        jobs.settle_analyze(job, False, int((time.monotonic() - started) * 1000))
        return {'status': 'failed'}
    finally:
        # 无论成败都清掉参考图；Redis 另有一层 TTL 兜底。
        remix_reference.drop(token)
