"""Owner-only paid-order reporting; monetary amounts stay Decimal."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse
from . import accounts

router=APIRouter()
OWNER='gelen5@163.com'
TZ=timezone(timedelta(hours=8))
PAID={'PAID','REFUNDED','PARTIAL_REFUNDED'}

def require_owner(request):
    user=accounts.require_admin(request)
    if user.get('email','').lower()!=OWNER or user.get('impersonation'):
        raise HTTPException(403,'仅站长本人可查看')
    return user

def day(value):
    if not value:return None
    try:
        dt=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return (dt.astimezone(TZ) if dt.tzinfo else dt.replace(tzinfo=TZ)).date()
    except (ValueError,TypeError):return None

def money(v):
    return Decimal(str(v or '0')).quantize(Decimal('0.01'))

def calculate(rows,start,end,today):
    confirmed=[r for r in rows if r['status'] in PAID]
    gross=sum((money(r['total_amount']) for r in confirmed),Decimal(0))
    refunds=sum((money(r['refunded_amount']) for r in confirmed),Decimal(0))
    selected=[r for r in confirmed if day(r['paid_at']) and start<=day(r['paid_at'])<=end]
    today_rows=[r for r in confirmed if day(r['paid_at'])==today]
    daily=[]; current=start
    while current<=end:
        group=[r for r in selected if day(r['paid_at'])==current]
        daily.append({'date':current.isoformat(),'amount':str(sum((money(r['total_amount']) for r in group),Decimal(0))),'count':len(group)})
        current+=timedelta(days=1)
    packages={}
    for r in selected:
        key=r['subject'] or '其他'
        item=packages.setdefault(key,{'name':key,'amount':Decimal(0),'count':0})
        item['amount']+=money(r['total_amount']);item['count']+=1
    return {'lifetime_paid':str(gross),'lifetime_refunded':str(refunds),'lifetime_net':str(gross-refunds),'today_paid':str(sum((money(r['total_amount']) for r in today_rows),Decimal(0))),'period_paid':str(sum((money(r['total_amount']) for r in selected),Decimal(0))),'period_count':len(selected),'missing_paid_time':sum(day(r['paid_at']) is None for r in confirmed),'daily':daily,'packages':[dict(x,amount=str(x['amount'])) for x in sorted(packages.values(),key=lambda x:x['amount'],reverse=True)],'orders':sorted(selected,key=lambda r:r['paid_at'] or '',reverse=True)}

@router.get('/owner-revenue',include_in_schema=False)
def page(request:Request):
    require_owner(request)
    return FileResponse(Path(__file__).resolve().parent.parent/'static'/'owner-revenue.html',headers={'Cache-Control':'no-store'})

@router.get('/api/owner-revenue')
def data(request:Request,start:str='',end:str='',page:int=1):
    require_owner(request)
    today=datetime.now(TZ).date()
    try:
        first=date.fromisoformat(start) if start else today-timedelta(days=6)
        last=date.fromisoformat(end) if end else today
    except ValueError:raise HTTPException(422,'日期格式无效')
    if last<first or (last-first).days>90:raise HTTPException(422,'请选择不超过 91 天的时间范围')
    with accounts._connect() as c:
        rows=[dict(r) for r in c.execute("""SELECT o.out_trade_no,o.subject,o.total_amount,o.status,o.refunded_amount,o.created_at,o.paid_at,r.package_id,r.credits,u.email FROM alipay_orders o JOIN alipay_recharges r ON o.out_trade_no=r.out_trade_no LEFT JOIN users u ON u.id=r.user_id ORDER BY o.created_at DESC""").fetchall()]
    result=calculate(rows,first,last,today)
    orders=result.pop('orders'); page=max(1,page)
    result.update({'orders':orders[(page-1)*20:page*20],'total_orders':len(orders),'page':page,'start':first.isoformat(),'end':last.isoformat(),'updated_at':datetime.now(TZ).isoformat(),'refund_timing_available':False})
    return result
