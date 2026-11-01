"""A moderated, non-custodial wish board.

This module deliberately records support *intent* only.  It never moves money
between users; a future payment/settlement product needs its own compliance
review and ledger rather than reusing the workbench points wallet.
"""
from __future__ import annotations

import io
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, LargeBinary, MetaData, String, Table, Text, func, insert, select, update
from fastapi.responses import Response

from . import accounts, database
from .storage.service import get_storage

router = APIRouter(prefix="/api/wishes", tags=["wish-square"])
metadata = MetaData()
MAX_IMAGES = 8
MAX_IMAGE_BYTES = 8 * 1024 * 1024

wishes = Table(
    "wishes", metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(64), nullable=False, index=True),
    Column("title", String(80), nullable=False),
    Column("story", Text, nullable=False),
    Column("category", String(24), nullable=False),
    Column("target_kind", String(16), nullable=False),
    Column("target_text", String(120), nullable=False),
    Column("status", String(16), nullable=False, index=True),
    Column("display_name", String(40), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
)
wish_images = Table(
    "wish_images", metadata,
    Column("id", String(32), primary_key=True),
    Column("wish_id", String(32), nullable=False, index=True),
    Column("storage_name", String(100), nullable=False),
    Column("content_type", String(32), nullable=False),
    Column("position", Integer, nullable=False),
)
wish_reviews = Table(
    "wish_reviews", metadata,
    Column("id", String(32), primary_key=True),
    Column("wish_id", String(32), nullable=False, index=True),
    Column("reviewer_id", String(64), nullable=False),
    Column("decision", String(16), nullable=False),
    Column("note", String(500), nullable=False),
    Column("created_at", String(40), nullable=False),
)
wish_supports = Table(
    "wish_supports", metadata,
    Column("id", String(32), primary_key=True),
    Column("wish_id", String(32), nullable=False, index=True),
    Column("user_id", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
)
wish_payment_codes = Table('wish_payment_codes', metadata, Column('wish_id', String(32), primary_key=True), Column('image', LargeBinary, nullable=False))
wish_transfers = Table('wish_transfers', metadata, Column('id', String(32), primary_key=True), Column('wish_id', String(32), nullable=False, index=True), Column('supporter_id', String(64), nullable=False), Column('amount', String(32), nullable=False), Column('message', String(500), nullable=False), Column('status', String(16), nullable=False), Column('created_at', String(40), nullable=False))
wish_reports = Table('wish_reports', metadata, Column('id', String(32), primary_key=True), Column('wish_id', String(32), nullable=False, index=True), Column('reporter_id', String(64), nullable=False), Column('reason', String(500), nullable=False), Column('created_at', String(40), nullable=False))


def init_schema() -> None:
    metadata.create_all(database.ENGINE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user(request: Request) -> dict | None:
    return getattr(request.state, "user", None) or accounts.user_from_request(request)


def _require_user(request: Request) -> dict:
    return _user(request) or accounts.require_user(request)


def _is_owner_or_admin(row: dict, user: dict | None) -> bool:
    return bool(user and (user.get("role") == "admin" or row["user_id"] == user.get("id")))


class WishCreate(BaseModel):
    title: str = Field(min_length=4, max_length=80)
    story: str = Field(min_length=20, max_length=2000)
    category: str = Field(default="生活改善", max_length=24)
    target_kind: str = Field(default="物品", pattern="^(物品|服务|小额资金|其他)$")
    target_text: str = Field(min_length=2, max_length=120)
    display_name: str = Field(min_length=1, max_length=40)


class ReviewBody(BaseModel):
    decision: str = Field(pattern="^(published|rejected|closed)$")
    note: str = Field(default="", max_length=500)


def _public(row: dict, image_count: int = 0, supports: int = 0, mine: bool = False) -> dict:
    value = dict(row)
    value.pop("user_id", None)
    value["image_count"] = image_count
    value["support_count"] = supports
    value["can_manage"] = mine
    return value


def _record(row: dict, user: dict | None = None) -> dict:
    with database.ENGINE.connect() as connection:
        image_rows = connection.execute(select(wish_images).where(wish_images.c.wish_id == row["id"]).order_by(wish_images.c.position)).mappings().all()
        supports = connection.execute(select(func.count()).select_from(wish_supports).where(wish_supports.c.wish_id == row["id"])).scalar_one()
        has_code = connection.execute(select(wish_payment_codes.c.wish_id).where(wish_payment_codes.c.wish_id == row['id'])).first() is not None
    item = _public(row, len(image_rows), int(supports or 0), _is_owner_or_admin(row, user))
    item["images"] = [f"/api/wishes/{row['id']}/images/{image['id']}" for image in image_rows]
    item['has_payment_code'] = has_code
    item['is_owner'] = bool(user and row['user_id'] == user.get('id'))
    return item


@router.get("")
def list_wishes(request: Request, mine: bool = False):
    user = _user(request)
    if mine:
        user = _require_user(request)
    with database.ENGINE.connect() as connection:
        query = select(wishes).order_by(wishes.c.created_at.desc())
        query = query.where(wishes.c.user_id == user["id"]) if mine else query.where(wishes.c.status == "published")
        rows = connection.execute(query.limit(60)).mappings().all()
    return {"items": [_record(dict(row), user) for row in rows]}


@router.post("", status_code=201)
def create_wish(payload: WishCreate, request: Request):
    user = _require_user(request)
    now = _now()
    wish_id = uuid.uuid4().hex
    clean = {name: re.sub(r"\s+", " ", str(getattr(payload, name)).strip()) for name in ("title", "story", "category", "target_kind", "target_text", "display_name")}
    with database.ENGINE.begin() as connection:
        connection.execute(insert(wishes).values(id=wish_id, user_id=user["id"], status="draft", created_at=now, updated_at=now, **clean))
        row = connection.execute(select(wishes).where(wishes.c.id == wish_id)).mappings().one()
    return _record(dict(row), user)


@router.post("/{wish_id}/images", status_code=201)
async def upload_image(wish_id: str, request: Request, image: UploadFile = File(...)):
    user = _require_user(request)
    with database.ENGINE.connect() as connection:
        row = connection.execute(select(wishes).where(wishes.c.id == wish_id)).mappings().first()
        current = connection.execute(select(func.count()).select_from(wish_images).where(wish_images.c.wish_id == wish_id)).scalar_one()
    if not row or not _is_owner_or_admin(dict(row), user):
        raise HTTPException(status_code=404, detail="心愿不存在")
    if row["status"] not in {"draft", "rejected"}:
        raise HTTPException(status_code=409, detail="审核完成后不能修改图片")
    if int(current or 0) >= MAX_IMAGES:
        raise HTTPException(status_code=422, detail="每个心愿最多上传 8 张图片")
    declared = image.content_type or ""
    if declared not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="仅支持 JPG、PNG 或 WebP 图片")
    raw = await image.read(MAX_IMAGE_BYTES + 1)
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="单张图片不能为空且不能超过 8MB")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            source = source.convert("RGB")
            source.thumbnail((2000, 2000))
            output = io.BytesIO()
            source.save(output, format="JPEG", quality=88, optimize=True)
            encoded = output.getvalue()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="图片文件无法解析") from exc
    image_id = uuid.uuid4().hex
    storage = get_storage()
    key = f"wishes/{wish_id}/{image_id}.jpg"
    try:
        stored = storage.upload(key, encoded, content_type="image/jpeg")
    except Exception as exc:
        raise HTTPException(status_code=502, detail="图片保存失败，请稍后重试") from exc
    try:
        with database.ENGINE.begin() as connection:
            position = connection.execute(select(func.count()).select_from(wish_images).where(wish_images.c.wish_id == wish_id)).scalar_one()
            if int(position or 0) >= MAX_IMAGES:
                raise HTTPException(status_code=422, detail="每个心愿最多上传 8 张图片")
            connection.execute(insert(wish_images).values(id=image_id, wish_id=wish_id, storage_name=stored.key, content_type=stored.content_type, position=int(position or 0)))
    except Exception:
        storage.delete(stored.key)
        raise
    return {"id": image_id, "url": f"/api/wishes/{wish_id}/images/{image_id}"}


@router.get("/{wish_id}/images/{image_id}")
def get_image(wish_id: str, image_id: str, request: Request):
    user = _user(request)
    with database.ENGINE.connect() as connection:
        wish = connection.execute(select(wishes).where(wishes.c.id == wish_id)).mappings().first()
        image = connection.execute(select(wish_images).where(wish_images.c.id == image_id, wish_images.c.wish_id == wish_id)).mappings().first()
    if not wish or not image or (wish["status"] != "published" and not _is_owner_or_admin(dict(wish), user)):
        raise HTTPException(status_code=404, detail="图片不存在")
    try:
        path = get_storage().local_path(image["storage_name"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="图片不存在")
    if path is None:
        return RedirectResponse(get_storage().get_url(image["storage_name"]), status_code=307)
    return FileResponse(path, media_type=image["content_type"], headers={"Cache-Control": "private, max-age=86400"})


@router.post("/{wish_id}/support", status_code=201)
def support_intent(wish_id: str, request: Request):
    user = _require_user(request)
    with database.ENGINE.begin() as connection:
        wish = connection.execute(select(wishes).where(wishes.c.id == wish_id, wishes.c.status == "published")).mappings().first()
        if not wish:
            raise HTTPException(status_code=404, detail="心愿不存在或尚未公开")
        if wish["user_id"] == user["id"]:
            raise HTTPException(status_code=422, detail="不能支持自己发布的心愿")
        existing = connection.execute(select(wish_supports.c.id).where(wish_supports.c.wish_id == wish_id, wish_supports.c.user_id == user["id"])).first()
        if not existing:
            connection.execute(insert(wish_supports).values(id=uuid.uuid4().hex, wish_id=wish_id, user_id=user["id"], created_at=_now()))
    return {"message": "已记录你的支持意愿。是否转账由你自行决定。"}


@router.post('/{wish_id}/payment-code')
async def upload_payment_code(wish_id: str, request: Request, image: UploadFile = File(...)):
    user = _require_user(request)
    with database.ENGINE.connect() as connection:
        row = connection.execute(select(wishes).where(wishes.c.id == wish_id)).mappings().first()
    if not row or row['user_id'] != user['id'] or row['status'] != 'draft':
        raise HTTPException(404, '心愿不存在或不可修改')
    if image.content_type not in {'image/jpeg', 'image/png', 'image/webp'}:
        raise HTTPException(415, '仅支持 JPG、PNG 或 WebP 图片')
    raw = await image.read(MAX_IMAGE_BYTES + 1)
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, '图片不能为空且不能超过 8MB')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.verify()
        with Image.open(io.BytesIO(raw)) as source:
            source = source.convert('RGB'); source.thumbnail((2000, 2000))
            output = io.BytesIO(); source.save(output, format='PNG'); raw = output.getvalue()
    except Exception as exc:
        raise HTTPException(422, '图片无法解析') from exc
    with database.ENGINE.begin() as connection:
        existing = connection.execute(select(wish_payment_codes.c.wish_id).where(wish_payment_codes.c.wish_id == wish_id)).first()
        if existing: connection.execute(update(wish_payment_codes).where(wish_payment_codes.c.wish_id == wish_id).values(image=raw))
        else: connection.execute(insert(wish_payment_codes).values(wish_id=wish_id, image=raw))
    return {'ok': True}


@router.post('/{wish_id}/submit')
def submit_wish(wish_id: str, request: Request):
    user = _require_user(request)
    with database.ENGINE.begin() as connection:
        result = connection.execute(update(wishes).where(wishes.c.id == wish_id, wishes.c.user_id == user['id'], wishes.c.status == 'draft').values(status='pending', updated_at=_now()))
        if result.rowcount != 1: raise HTTPException(404, '草稿不存在或已提交')
    return {'ok': True}


@router.get('/{wish_id}/payment-code')
def payment_code(wish_id: str, request: Request):
    user = _require_user(request)
    with database.ENGINE.connect() as connection:
        row = connection.execute(select(wishes).where(wishes.c.id == wish_id)).mappings().first()
        code = connection.execute(select(wish_payment_codes.c.image).where(wish_payment_codes.c.wish_id == wish_id)).first()
    if not row or not code or (row['status'] != 'published' and not _is_owner_or_admin(dict(row), user)):
        raise HTTPException(404, '收款码不存在')
    return Response(content=bytes(code[0]), media_type='image/png', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options':'nosniff'})


class TransferBody(BaseModel):
    amount: str = Field(default='', max_length=32, pattern=r'^$|^\d{1,8}(\.\d{1,2})?$')
    message: str = Field(default='', max_length=500)


@router.post('/{wish_id}/transfers', status_code=201)
def register_transfer(wish_id: str, payload: TransferBody, request: Request):
    user = _require_user(request)
    with database.ENGINE.begin() as connection:
        wish = connection.execute(select(wishes).where(wishes.c.id == wish_id, wishes.c.status == 'published')).mappings().first()
        if not wish or wish['user_id'] == user['id']: raise HTTPException(404, '心愿不存在或不可操作')
        if not connection.execute(select(wish_payment_codes.c.wish_id).where(wish_payment_codes.c.wish_id == wish_id)).first(): raise HTTPException(409, '该心愿没有收款码')
        connection.execute(insert(wish_transfers).values(id=uuid.uuid4().hex, wish_id=wish_id, supporter_id=user['id'], amount=payload.amount, message=payload.message.strip(), status='pending', created_at=_now()))
    return {'message':'已登记，等待发布者确认；平台无法核实转账。'}


@router.get('/mine/transfers')
def my_transfers(request: Request):
    user = _require_user(request)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(wish_transfers.c.id, wish_transfers.c.amount, wish_transfers.c.message, wish_transfers.c.status, wish_transfers.c.created_at, wishes.c.title).join(wishes, wishes.c.id == wish_transfers.c.wish_id).where(wishes.c.user_id == user['id']).order_by(wish_transfers.c.created_at.desc()).limit(100)).mappings().all()
    return {'items':[dict(row) for row in rows]}


@router.post('/transfers/{transfer_id}/confirm')
def confirm_transfer(transfer_id: str, request: Request):
    user = _require_user(request)
    with database.ENGINE.begin() as connection:
        transfer = connection.execute(select(wish_transfers, wishes.c.user_id).join(wishes, wishes.c.id == wish_transfers.c.wish_id).where(wish_transfers.c.id == transfer_id)).mappings().first()
        if not transfer or transfer['user_id'] != user['id']: raise HTTPException(404, '记录不存在')
        connection.execute(update(wish_transfers).where(wish_transfers.c.id == transfer_id).values(status='confirmed'))
    return {'message':'已记录发布者确认，平台未核实支付。'}


class ReportBody(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


@router.post('/{wish_id}/report')
def report_wish(wish_id: str, payload: ReportBody, request: Request):
    user = _require_user(request)
    with database.ENGINE.begin() as connection:
        if not connection.execute(select(wishes.c.id).where(wishes.c.id == wish_id, wishes.c.status == 'published')).first(): raise HTTPException(404, '心愿不存在')
        connection.execute(insert(wish_reports).values(id=uuid.uuid4().hex, wish_id=wish_id, reporter_id=user['id'], reason=payload.reason.strip(), created_at=_now()))
    return {'message':'举报已提交。'}


@router.get("/admin/review")
def review_queue(request: Request, status: str = "pending"):
    accounts.require_admin(request)
    if status not in {"pending", "published", "rejected", "closed", "all"}:
        raise HTTPException(status_code=422, detail="无效的审核状态")
    with database.ENGINE.connect() as connection:
        query = select(wishes).order_by(wishes.c.created_at.asc())
        if status != "all":
            query = query.where(wishes.c.status == status)
        rows = connection.execute(query.limit(100)).mappings().all()
    items = [_record(dict(row), {"role": "admin"}) for row in rows]
    with database.ENGINE.connect() as connection:
        for item in items:
            item['reports'] = [dict(r) for r in connection.execute(select(wish_reports.c.reason, wish_reports.c.created_at).where(wish_reports.c.wish_id == item['id']).order_by(wish_reports.c.created_at.desc())).mappings().all()]
    return {"items": items}


@router.post("/{wish_id}/review")
def review_wish(wish_id: str, payload: ReviewBody, request: Request):
    admin = accounts.require_admin(request)
    now = _now()
    with database.ENGINE.begin() as connection:
        row = connection.execute(select(wishes).where(wishes.c.id == wish_id)).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="心愿不存在")
        if payload.decision in {'published', 'rejected'} and row['status'] != 'pending':
            raise HTTPException(status_code=409, detail='只有待审核的心愿可以通过或驳回')
        connection.execute(update(wishes).where(wishes.c.id == wish_id).values(status=payload.decision, updated_at=now))
        connection.execute(insert(wish_reviews).values(id=uuid.uuid4().hex, wish_id=wish_id, reviewer_id=admin["id"], decision=payload.decision, note=payload.note.strip(), created_at=now))
        updated = connection.execute(select(wishes).where(wishes.c.id == wish_id)).mappings().one()
    return _record(dict(updated), admin)
