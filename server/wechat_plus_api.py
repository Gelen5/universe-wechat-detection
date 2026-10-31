"""Owner-scoped endpoints; existing workbench routes are deliberately untouched."""
from copy import deepcopy
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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
            'pricing': 'Plus 内测期间暂不扣积分'}


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
    limit = check_agent_submission(owner(request), client_ip(request), 'wechat_plus')
    if not limit.allowed:
        raise HTTPException(429, '操作较频繁，请稍后再试', headers={'Retry-After': str(limit.retry_after)})
    try:
        turn, created = repo.enqueue(session_id, owner(request), payload.version,
                                     payload.message.strip(), payload.idempotency_key)
    except KeyError as exc:
        raise HTTPException(404, '创作不存在') from exc
    except repo.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if created:
        try:
            tasks.dispatch(turn['id'])
        except Exception:
            # The queued row is the outbox; beat will safely dispatch it later.
            pass
    return {'turn': {key:value for key,value in turn.items() if key != 'cache'}}


@router.post('/sessions/{session_id}/cancel/{turn_id}')
def cancel(session_id: str, turn_id: str, request: Request):
    row = get(session_id, request)
    if not any(turn['id'] == turn_id for turn in row['turns']):
        raise HTTPException(404, '操作不存在')
    return {'cancelled': repo.cancel(turn_id, owner(request))}


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
    limit = check_agent_submission(owner(request), client_ip(request), 'wechat_plus')
    if not limit.allowed:
        raise HTTPException(429, '操作较频繁，请稍后再试')
    try:
        turn = repo.retry(session_id, turn_id, owner(request))
    except KeyError as exc:
        raise HTTPException(404, '操作不存在') from exc
    except repo.Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    try:
        tasks.dispatch(turn_id)
    except Exception:
        pass
    return {'turn': {key:value for key,value in turn.items() if key != 'cache'}}


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
