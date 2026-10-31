import os, uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import MetaData, Table, Column, String, Text, insert, select
from . import accounts, database
router=APIRouter()
metadata=MetaData()
feedback=Table('community_feedback',metadata,Column('id',String(32),primary_key=True),Column('user_id',String(64),nullable=False),Column('category',String(40)),Column('body',Text),Column('page',String(300)),Column('contact',String(200)),Column('created_at',String(40)))
def init_schema():
    metadata.create_all(database.ENGINE)
class FeedbackRequest(BaseModel):
    category:str=Field(default='问题反馈',max_length=40)
    body:str=Field(min_length=5,max_length=4000)
    page:str=Field(default='',max_length=300)
    contact:str=Field(default='',max_length=200)
@router.get('/api/community')
def community():
    return {'group_url':os.getenv('COMMUNITY_GROUP_URL',''),'updates':[{'date':'2026-10-31','title':'快点我，上线了','items':['集中提交问题和功能建议','群聊入口与更新记录统一收录']},{'date':'2026-10-31','title':'近期工作台更新','items':['贴图复刻支持最多8张参考图','文字与画面由图片模型一体生成','发布前复核统一薄荷绿主题']}]}
@router.post('/api/community/feedback')
def submit(payload:FeedbackRequest,request:Request):
    user=accounts.require_user(request)
    key=uuid.uuid4().hex
    with database.ENGINE.begin() as connection:
        connection.execute(insert(feedback).values(id=key,user_id=user['id'],category=payload.category,body=payload.body.strip(),page=payload.page,contact=payload.contact,created_at=datetime.now(timezone.utc).isoformat()))
    return {'id':key,'message':'反馈已保存，感谢你的建议。'}
@router.get('/api/admin/community/feedback')
def inbox(request:Request):
    accounts.require_admin(request)
    with database.ENGINE.connect() as connection:
        return {'items':[dict(r) for r in connection.execute(select(feedback).order_by(feedback.c.created_at.desc()).limit(100)).mappings()]}
