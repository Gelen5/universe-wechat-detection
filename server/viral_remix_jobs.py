"""爆款贴图复刻的异步出图任务。

为什么改异步：一次最多 8 张，每张 25~35 秒，同步接口要跑 3~4 分钟，网关先超时，
图片却还在生成——用户看到 502、钱收了、图留下。改成「提交 → 轮询」，前端还能
用 job_id 在切走菜单再回来时把进度接上。

计费：一张 2 积分。提交时按张数预扣（最多 8 张 = 16 积分），每画完一张记一次
进度，结束时按**实际成功**的张数结算，余量原路退回；一张都没成则全额退。
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from . import accounts, creator_tools

LANE = 'image'
TASK_TYPE = 'viral_remix.image'
PROGRESS_STAGES = {'preparing': '正在展开创意', 'generating': '正在出图', 'validating':'正在检查成图', 'repairing':'正在修复成图'}


def job_key(session_id: str, idea: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(['data-impact-type-v3' if idea.get('data_contract') else 'image-v1', session_id, idea], sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:40]
    return 'viral-remix:' + digest


def count_cards(idea: dict[str, Any]) -> int:
    cards = idea.get('cards')
    if cards is None:          # 没给计划时按单张处理（与 creator_tools 一致）
        count = idea.get('page_count', 1)
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= accounts.VIRAL_REMIX_MAX_CARDS:
            raise ValueError('方案页数须为1到8张')
        return count
    if not isinstance(cards, list) or not 1 <= len(cards) <= accounts.VIRAL_REMIX_MAX_CARDS:
        raise ValueError('原创卡片数量须为1到8张')
    return len(cards)


def submit(user_id: str, session_id: str, idea: dict[str, Any]) -> dict[str, Any]:
    """预扣积分 + 建任务。返回 jobs 表的一行（调用方负责 dispatch）。"""
    count = count_cards(idea)
    usage_id = accounts.reserve_points(
        user_id, accounts.viral_remix_rule(count), 'POST', '/api/viral-remix/image')
    try:
        job = accounts.create_job(
            user_id, TASK_TYPE, LANE, job_key(session_id, idea), usage_id,
            {'session_id': session_id, 'idea': idea, 'count': count})
    except Exception:
        accounts.refund_usage(usage_id, 500, 0)
        raise
    if not job:
        accounts.refund_usage(usage_id, 500, 0)
        raise RuntimeError('任务创建失败')
    # 幂等重放：同一个创意重复提交时 create_job 返回旧行，本次预扣要退掉。
    if job.get('usage_id') and job['usage_id'] != usage_id:
        accounts.refund_usage(usage_id, 200, 0)
    return job


def is_fresh(job: dict[str, Any], usage_id: str) -> bool:
    return bool(job.get('usage_id') == usage_id)


def public(job: dict[str, Any]) -> dict[str, Any]:
    """jobs 行 → 前端结构。进度存在 result_json.progress 里。"""
    payload: dict[str, Any] = {}
    result: dict[str, Any] = {}
    try:
        payload = json.loads(job.get('payload_json') or '{}')
    except Exception:  # noqa: BLE001
        payload = {}
    try:
        result = json.loads(job.get('result_json') or '{}')
    except Exception:  # noqa: BLE001
        result = {}

    status = job.get('status') or 'queued'
    progress = result.get('progress') or {}
    total = int(payload.get('count') or 0)
    done = int(progress.get('done') or 0)
    images = result.get('images') or []
    if status == 'succeeded':
        done = len(images) or done

    return {
        'id': job.get('id'),
        'status': status,
        'session_id': payload.get('session_id'),
        'total': total,
        'done': done,
        'stage': progress.get('stage') or ('完成' if status == 'succeeded' else '排队中'),
        'images': images,
        'publication': result.get('publication'),
        'copy_directions': result.get('copy_directions') or [],
        'tags': result.get('tags') or {},
        'warning': result.get('warning') or '',
        'error': job.get('error') or '',
        'points': {'per_image': accounts.VIRAL_REMIX_POINTS_PER_IMAGE,
                   'reserved': total * accounts.VIRAL_REMIX_POINTS_PER_IMAGE,
                   'charged': len(images) * accounts.VIRAL_REMIX_POINTS_PER_IMAGE
                   if status == 'succeeded' else 0},
        'created_at': job.get('created_at'),
        'finished_at': job.get('finished_at'),
    }


def settle(job: dict[str, Any], images: list[dict[str, Any]], elapsed_ms: int) -> None:
    """按实际出图张数结算；没有出图就全额退。"""
    usage_id = job.get('usage_id')
    if not usage_id:
        return
    charged = len(images) * accounts.VIRAL_REMIX_POINTS_PER_IMAGE
    if charged > 0:
        accounts.settle_usage_with_points(usage_id, 200, elapsed_ms, charged)
    else:
        accounts.refund_usage(usage_id, 200, elapsed_ms)


# ---------------------------------------------------------------- 拆解（视觉分析）
# 拆解是纯视觉分析，一次 2 积分（规则沿用 POST /api/viral-remix/analyze）。
# 同步接口在手机上要吊 2 分半长连接，实测会被移动网关吞掉响应，所以改成
# 「提交 → 轮询」：参考图先进 Redis（见 remix_reference.py），任务只带 token。
ANALYZE_TASK_TYPE = 'viral_remix.analyze'
ANALYZE_LANE = 'text'
ANALYZE_PATH = '/api/viral-remix/analyze'
ANALYZE_STAGES = {'queued': '排队中', 'running': '正在拆解图片结构'}


def analyze_key(session_id: str, token: str, goal: str, preserve_person: bool) -> str:
    digest = hashlib.sha256(
        json.dumps(['analysis-v1', session_id, token, goal, bool(preserve_person)],
                   sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:40]
    return 'viral-remix-analyze:' + digest


def submit_analyze(user_id: str, session_id: str, token: str, goal: str = '',
                   preserve_person: bool = False) -> dict[str, Any]:
    """预扣 2 积分 + 建拆解任务。返回 jobs 表的一行（调用方负责 dispatch）。"""
    rule = accounts.pricing_rule('POST', ANALYZE_PATH)
    if not rule:
        raise RuntimeError('拆解计费规则未启用')
    usage_id = accounts.reserve_points(user_id, rule, 'POST', ANALYZE_PATH)
    try:
        job = accounts.create_job(
            user_id, ANALYZE_TASK_TYPE, ANALYZE_LANE,
            analyze_key(session_id, token, goal, preserve_person), usage_id,
            {'session_id': session_id, 'token': token, 'goal': goal,
             'preserve_person': bool(preserve_person)})
    except Exception:
        accounts.refund_usage(usage_id, 500, 0)
        raise
    if not job:
        accounts.refund_usage(usage_id, 500, 0)
        raise RuntimeError('任务创建失败')
    # 幂等重放：同一个 token 重复提交时返回旧行，本次预扣要退掉。
    if job.get('usage_id') and job['usage_id'] != usage_id:
        accounts.refund_usage(usage_id, 200, 0)
    return job


def public_analyze(job: dict[str, Any]) -> dict[str, Any]:
    """jobs 行 → 前端结构；拆解结果放在 result 顶层，与旧同步接口返回一致。"""
    payload: dict[str, Any] = {}
    result: dict[str, Any] = {}
    try:
        payload = json.loads(job.get('payload_json') or '{}')
    except Exception:  # noqa: BLE001
        payload = {}
    try:
        result = json.loads(job.get('result_json') or '{}')
    except Exception:  # noqa: BLE001
        result = {}
    status = job.get('status') or 'queued'
    return {
        'id': job.get('id'),
        'status': status,
        'session_id': payload.get('session_id'),
        'stage': ANALYZE_STAGES.get(status) or ('拆解完成' if status == 'succeeded' else '正在拆解图片结构'),
        'result': result.get('result') if status == 'succeeded' else None,
        'error': job.get('error') or '',
        'created_at': job.get('created_at'),
        'finished_at': job.get('finished_at'),
    }


def settle_analyze(job: dict[str, Any], succeeded: bool, elapsed_ms: int) -> None:
    """拆解只有成/不成两态：成则结算 2 积分，失败全额退回。"""
    usage_id = job.get('usage_id')
    if not usage_id:
        return
    if succeeded:
        accounts.settle_usage(usage_id, 200, elapsed_ms)
    else:
        accounts.refund_usage(usage_id, 500, elapsed_ms)


__all__ = ['LANE', 'TASK_TYPE', 'count_cards', 'submit', 'public', 'settle', 'creator_tools',
           'ANALYZE_TASK_TYPE', 'ANALYZE_LANE', 'ANALYZE_PATH',
           'submit_analyze', 'public_analyze', 'settle_analyze']
