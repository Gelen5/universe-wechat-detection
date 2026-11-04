"""Owner-scoped single-image creation and revision endpoints."""
from __future__ import annotations
import json
import uuid
from fastapi import APIRouter,HTTPException,Request
from pydantic import BaseModel,Field
from . import accounts,remix_studio,viral_remix_jobs as jobs,viral_remix_tasks as tasks

router=APIRouter(prefix='/api/remix-studio',tags=['remix-studio'])


class Create(BaseModel):
    imageData: str = Field(max_length=14_000_000)
    goal: str = Field(default='',max_length=1200)
    options: list[str] = Field(default_factory=list,max_length=6)
    requestId: str = Field(min_length=8,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')


class Revise(BaseModel):
    goal: str = Field(default='',max_length=1200)
    options: list[str] = Field(default_factory=list,max_length=6)
    requestId: str = Field(min_length=8,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')


def public(job):
    view=jobs.public(job)
    payload=json.loads(job.get('payload_json') or '{}')
    studio=(payload.get('idea') or {}).get('studio') or {}
    result=json.loads(job.get('result_json') or '{}')
    return {**view,'studio':True,'parent_id':studio.get('parent_id'),
            'goal':studio.get('goal',''),'options':studio.get('options',[]),
            'session_id':payload.get('session_id'), 'design':result.get('design'),
            'acceptance':result.get('acceptance')}


def own(job_id,user):
    job=accounts.job(job_id,user['id'])
    if not job or not (json.loads(job.get('payload_json') or '{}').get('idea') or {}).get('studio'):
        raise HTTPException(404,'创作记录不存在')
    return job


def submit(user,request_id,studio,session_id):
    key='remix-studio:'+request_id
    # Replays return the original job even when the wallet has since changed.
    with accounts.conversation_lock(key,user['id']):
        with accounts._connect() as db:
            old=db.execute('SELECT * FROM jobs WHERE user_id=? AND idempotency_key=?',(user['id'],key)).fetchone()
        if old: return dict(old)
        usage=accounts.reserve_points(user['id'],accounts.viral_remix_rule(1),'POST','/api/remix-studio/create')
        try:
            job=accounts.create_job(user['id'],jobs.TASK_TYPE,jobs.LANE,key,usage,
                {'session_id':session_id,'count':1,'idea':{'studio':studio,'cards':[{}]}})
            if not job: raise RuntimeError('任务创建失败')
        except Exception:
            accounts.refund_usage(usage,500,0)
            raise
        if job.get('usage_id')!=usage: accounts.refund_usage(usage,200,0)
    try: tasks.dispatch(job['id'])
    except Exception:
        accounts.fail_job(job['id'],'任务暂时无法启动，请稍后重试；预扣积分已退还。')
        jobs.settle(job,[],0)
        job=accounts.job(job['id'],user['id'])
    return job


@router.post('/create',status_code=202)
def create(payload:Create,request:Request):
    user=accounts.require_user(request)
    try:
        source=remix_studio.validate_reference(payload.imageData)
        remix_studio.option_text(payload.options)
        job=submit(user,payload.requestId,{'version':1,'reference':source,'goal':payload.goal,
            'options':payload.options},uuid.uuid4().hex)
        return {'job':public(job)}
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc


@router.post('/{job_id}/revise',status_code=202)
def revise(job_id:str,payload:Revise,request:Request):
    user=accounts.require_user(request)
    parent=own(job_id,user)
    if parent['status']!='succeeded': raise HTTPException(409,'请等待成图完成后再修改')
    if not payload.goal.strip() and not payload.options: raise HTTPException(422,'请选择修改方向或写下修改要求')
    try:
        remix_studio.option_text(payload.options,True)
        old_payload=json.loads(parent['payload_json'])
        prior=old_payload['idea']['studio']
        job=submit(user,payload.requestId,{'version':1,'reference':prior['reference'],
            'original_options':prior.get('original_options',prior.get('options',[])),
            'original_goal':prior.get('original_goal',prior.get('goal','')),
            'parent_id':job_id,'goal':payload.goal,'options':payload.options},old_payload['session_id'])
        return {'job':public(job)}
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc


@router.get('/history')
def history(request:Request,before:str=''):
    user=accounts.require_user(request)
    sql='SELECT * FROM jobs WHERE user_id=? AND type=? AND payload_json LIKE ?'
    params=[user['id'],jobs.TASK_TYPE,'%"studio":%']
    if before:
        cursor=own(before,user)
        sql+=' AND (created_at<? OR (created_at=? AND id<?))'
        params.extend([cursor['created_at'],cursor['created_at'],cursor['id']])
    with accounts._connect() as db:
        rows=[dict(row) for row in db.execute(sql+' ORDER BY created_at DESC,id DESC LIMIT 41',params).fetchall()]
    return {'jobs':[public(job) for job in rows[:40]],'next_before':rows[39]['id'] if len(rows)>40 else None}


@router.get('/jobs/{job_id}')
def status(job_id:str,request:Request):
    return {'job':public(own(job_id,accounts.require_user(request)))}
