"""Owner-scoped endpoints; existing workbench routes are deliberately untouched."""
from copy import deepcopy
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import accounts
from . import wechat_plus_billing as billing
from . import wechat_plus_repository as repo
from . import wechat_plus_service as service
from . import wechat_plus_tasks as tasks
from . import workbench
from .rate_limit import check_agent_submission
from .auth_rate_limit import client_ip

router = APIRouter(prefix='/api/wechat-plus', tags=['wechat-plus'])


def owner(request):
    user = getattr(request.state, 'user', None)
    if not user:
        raise HTTPException(401, '请先登录')
    return user['id']


def get(session_id, request):
    try:
        return repo.get(session_id, owner(request))
    except KeyError as exc:
        raise HTTPException(404, '创作不存在或不属于当前用户') from exc


class Create(BaseModel):
    title: str = Field(default='新创作', max_length=240)


class Message(BaseModel):
    message: str = Field(min_length=1, max_length=30000)
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)


class Edit(BaseModel):
    draft: str = Field(max_length=150000)
    version: int = Field(ge=1)


@router.get('/sessions')
def sessions(request: Request):
    return {'sessions': repo.list_sessions(owner(request)), 'model': service.configured_model(),
            'pricing': '按动作计费：推荐选题 2 · 生成初稿 12 · 改稿 6 · 复核 5 · 排版 2；澄清与追问免费',
            'pricing_points': dict(accounts.PLUS_ACTION_POINTS)}


@router.post('/sessions', status_code=201)
def create(payload: Create, request: Request):
    return {'session': repo.create(owner(request), payload.title)}


@router.get('/sessions/{session_id}')
def session(session_id: str, request: Request):
    return {'session': get(session_id, request)}


@router.post('/sessions/{session_id}/messages', status_code=202)
def message(session_id: str, payload: Message, request: Request):
    if not payload.message.strip():
        raise HTTPException(422, '请输入内容')
    user_id = owner(request)
    limit = check_agent_submission(user_id=user_id, ip=client_ip(request), skill_id='wechat_plus')
    if not limit.allowed:
        raise HTTPException(429, '操作较频繁，请稍后再试', headers={'Retry-After': str(limit.retry_after)})

    # 先按最高档预扣：这条路径承载多种动作，只有跑完才知道是闲聊(0) 还是成稿(12)。
    # 不够钱就在这里 402，不会出现「活干完了却扣不到分」。
    path = f'/api/wechat-plus/sessions/{session_id}/messages'
    usage_id = accounts.reserve_points(
        user_id, accounts.plus_rule(accounts.PLUS_MAX_POINTS), 'POST', path)

    try:
        turn, created = repo.enqueue(session_id, user_id, payload.version,
                                     payload.message.strip(), payload.idempotency_key)
    except KeyError as exc:
        accounts.refund_usage(usage_id, 404, 0)
        raise HTTPException(404, '创作不存在') from exc
    except repo.Conflict as exc:
        accounts.refund_usage(usage_id, 409, 0)
        raise HTTPException(409, str(exc)) from exc
    except Exception:
        accounts.refund_usage(usage_id, 500, 0)
        raise

    if created:
        billing.attach(turn['id'], usage_id)
    else:
        # 幂等重放：这次没有真的执行，退掉本次预扣，沿用原 turn 的那笔。
        accounts.refund_usage(usage_id, 200, 0)
        usage_id = billing.usage_for(turn['id'])

    if created:
        try:
            tasks.dispatch(turn['id'])
        except Exception:
            # The queued row is the outbox; beat will safely dispatch it later.
            pass
    result = {'turn': {key: value for key, value in turn.items() if key != 'cache'}}
    result['points'] = {'reserved': accounts.PLUS_MAX_POINTS, 'settles_by': 'action'}
    return result


@router.post('/sessions/{session_id}/cancel/{turn_id}')
def cancel(session_id: str, turn_id: str, request: Request):
    row = get(session_id, request)
    if not any(turn['id'] == turn_id for turn in row['turns']):
        raise HTTPException(404, '操作不存在')
    cancelled = repo.cancel(turn_id, owner(request))
    if cancelled:
        # 取消 = 没产出，预扣全额退回；已经结算过的不会命中 refund（状态不是 reserved）。
        usage_id = billing.usage_for(turn_id)
        if usage_id:
            accounts.refund_usage(usage_id, 499, 0)
            billing.record(turn_id, 'cancelled', 0)
    return {'cancelled': cancelled}


@router.put('/sessions/{session_id}/draft')
def edit(session_id: str, payload: Edit, request: Request):
    row = get(session_id, request)
    if any(turn['status'] in {'queued', 'running'} for turn in row['turns']):
        raise HTTPException(409, '请等待当前处理完成或先取消，再编辑正文')
    state = deepcopy(row['state'])
    if not state.get('article_state'):
        raise HTTPException(409, '请先创作或导入文章')
    service.record_version(state, '手动编辑前')
    state['article_state']['draft'] = payload.draft
    service.reset_from(state['article_state'], 'review')
    service.record_version(state, '手动编辑')
    try:
        return {'session': repo.save(session_id, owner(request), payload.version, state)}
    except repo.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/sessions/{session_id}/retry/{turn_id}', status_code=202)
def retry(session_id: str, turn_id: str, request: Request):
    user_id = owner(request)
    limit = check_agent_submission(user_id=user_id, ip=client_ip(request), skill_id='wechat_plus')
    if not limit.allowed:
        raise HTTPException(429, '操作较频繁，请稍后再试')
    # 重试不重复收费：上一笔预扣还挂着（worker 中途死掉）就继续用它；已经退过
    # （执行失败/取消）才重新预扣一次。
    usage_id = billing.usage_for(turn_id)
    reserved_now = False
    if not usage_id or accounts.usage_state(usage_id) != 'reserved':
        usage_id = accounts.reserve_points(
            user_id, accounts.plus_rule(accounts.PLUS_MAX_POINTS), 'POST',
            f'/api/wechat-plus/sessions/{session_id}/retry/{turn_id}')
        reserved_now = True
    try:
        turn = repo.retry(session_id, turn_id, user_id)
    except KeyError as exc:
        if reserved_now:
            accounts.refund_usage(usage_id, 404, 0)
        raise HTTPException(404, '操作不存在') from exc
    except repo.Conflict as exc:
        if reserved_now:
            accounts.refund_usage(usage_id, 409, 0)
        raise HTTPException(409, str(exc)) from exc
    billing.attach(turn_id, usage_id)
    try:
        tasks.dispatch(turn_id)
    except Exception:
        pass
    return {'turn': {key: value for key, value in turn.items() if key != 'cache'}}


@router.get('/sessions/{session_id}/preview')
def preview(session_id: str, request: Request):
    row = get(session_id, request)
    article = row['state'].get('article_state') or {}
    name = article.get('formatted_output')
    if not name:
        raise HTTPException(404, '请先生成排版预览')
    path = Path(name).resolve()
    base = (workbench.OUTPUT_DIR / 'wechat-plus' / session_id).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise HTTPException(404, '预览暂不可用，请重新排版')
    return FileResponse(path, media_type='text/html', headers={
        'Content-Security-Policy': "sandbox; default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; font-src 'none'"})
