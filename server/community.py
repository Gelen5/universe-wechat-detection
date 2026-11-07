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
    return {'group_url':os.getenv('COMMUNITY_GROUP_URL',''),'updates':[{'date':'2026-11-07','title':'成品库自动化','items':['新增从已有低粉、图文和热点快照选题并生成成品的管理员自动化，支持预算限制、质量检查、异常池和审核后上架。']},{'date':'2026-11-07','title':'爆款成品库上线','items':['新增独家买断的文章与贴图成品，购买后可在我的购买中查看。']},{'date':'2026-11-07','title':'爆文复刻上线','items':['支持基于公开文章换角度重写，可选择去 AI 味；开启为 13 积分，不开启为 10 积分。']},{'date':'2026-11-06','title':'贴图号图片设置','items':['贴图号创作新增图片文字选择，照片类可自动生成无字画面，并更重视你填写的画面风格要求。']},{'date':'2026-11-06','title':'贴图号人物设置','items':['贴图号创作支持选择是否使用人物及多张图的人物一致性，生成前可查看并调整。']},{'date':'2026-11-05','title':'选题灵感库上线','items':['新增按分类和赛道查找选题，支持搜索和账号收藏。']},{'date':'2026-11-05','title':'公众号创作升级','items':['公众号创作新增多种排版样式和文章表达优化，让成稿与排版更方便。']},{'date':'2026-11-04','title':'近期更新','items':['优化推荐选题与爆文转贴图的液态玻璃界面，打通热点直达公众号创作 Plus，新增模型失败自动降级与详细错误记录，并优化积分流水顺序及扣退分状态说明。']},{'date':'2026-10-31','title':'快点我，上线了','items':['集中提交问题与功能建议','群聊入口与更新记录统一收录']},{'date':'2026-10-31','title':'近期工作台更新','items':['贴图复刻支持最多8张参考图','文字与画面由图片模型一体生成','发布前复核统一薄荷绿主题']}]}
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
