"""Exclusive content products. All full content is served after authorization."""
from __future__ import annotations

import json
import hashlib
import re
import os
import requests
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError

from . import accounts, database
from .models import LowfansArticle
from .content_factory_purchase import (InsufficientPoints, PurchaseError, SoldOut,
                                       feedback, jobs, metadata, products, purchase)

router = APIRouter(prefix="/api/content-factory", tags=["content-factory"])
PUBLIC_COLUMNS = ("id", "status", "product_type", "title", "track", "preview", "price_points",
                  "source_title", "source_url", "source_date", "source_metrics", "published_at", "buyer_id")


def now():
    return datetime.now(timezone.utc).isoformat()


def ready():
    inspector = inspect(database.ENGINE)
    for table in metadata.sorted_tables:
        if not inspector.has_table(table.name):
            raise HTTPException(503, "成品库尚未完成数据库迁移")
        actual = {column["name"] for column in inspector.get_columns(table.name)}
        if not set(table.c.keys()).issubset(actual):
            raise HTTPException(503, "成品库数据库结构不完整")


def admin(request):
    ready()
    return accounts.require_admin(request)


def safe_source_url(url):
    try:
        parsed = urlparse(url or "")
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except ValueError:
        return False


def public(row, user_id=None):
    return {key: row[key] for key in ("id", "status", "product_type", "title", "track", "preview",
            "price_points", "source_title", "source_url", "source_date", "source_metrics", "published_at")} | {
        "owned": bool(user_id and row["buyer_id"] == user_id)}


class Draft(BaseModel):
    source_row_id: int
    product_type: str = Field(pattern="^(article|image)$")
    title: str = Field(min_length=1, max_length=240)
    track: str = Field(default="", max_length=80)
    preview: str = Field(default="", max_length=1000)
    content: str = Field(default="", max_length=60000)
    price_points: int = Field(ge=1, le=100000)


class Feedback(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class Generate(BaseModel):
    angle: str = Field(min_length=1, max_length=2000)


@router.post("/admin/products/{product_id}/generate")
def generate_product(product_id: str, payload: Generate, request: Request):
    admin(request)
    ident = uuid.uuid4().hex
    with database.ENGINE.begin() as connection:
        row = connection.execute(select(products).where(products.c.id == product_id).with_for_update()).mappings().first()
        if not row or row["status"] != "draft" or row["product_type"] != "article":
            raise HTTPException(409, "仅支持生成文章草稿")
        if connection.execute(select(jobs.c.id).where(jobs.c.product_id == product_id,
                jobs.c.status.in_(["queued", "running"]))).first():
            raise HTTPException(409, "已有生成任务")
        connection.execute(jobs.insert().values(id=ident, product_id=product_id, angle=payload.angle,
                                                status="queued", created_at=now()))
    try:
        from .content_factory_tasks import generate_article
        generate_article.apply_async(args=[ident], queue="chat")
    except Exception as exc:
        with database.ENGINE.begin() as connection:
            connection.execute(update(jobs).where(jobs.c.id == ident).values(status="failed", error="任务提交失败"))
        raise HTTPException(503, "生成任务提交失败，请重试") from exc
    return {"job_id": ident}


@router.get("/admin/jobs/{job_id}")
def job_status(job_id: str, request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        row = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
    if not row:
        raise HTTPException(404, "任务不存在")
    return dict(row)


@router.get("/sources")
def sources(request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(LowfansArticle).order_by(
            LowfansArticle.stat_date.desc(), LowfansArticle.rank_no).limit(200)).mappings().all()
    return [{"id": r["id"], "title": r["title"], "url": r["art_url"], "date": r["stat_date"],
             "read_num": r["read_num"], "boost_ratio": r["boost_ratio"]} for r in rows
            if r["art_id"] and r["title"] and safe_source_url(r["art_url"])]


@router.post("/admin/products")
def create_product(payload: Draft, request: Request):
    admin(request)
    with database.ENGINE.begin() as connection:
        source = connection.execute(select(LowfansArticle.__table__).where(
            LowfansArticle.id == payload.source_row_id)).mappings().first()
        if not source or not source["art_id"] or not source["title"] or not safe_source_url(source["art_url"]):
            raise HTTPException(400, "来源缺少有效链接或标题")
        ident = uuid.uuid4().hex
        connection.execute(products.insert().values(
            id=ident, status="draft", product_type=payload.product_type, title=payload.title,
            track=payload.track, preview=payload.preview, content=payload.content, price_points=payload.price_points,
            source_id=source["art_id"], source_title=source["title"], source_url=source["art_url"],
            source_date=source["stat_date"], source_metrics=json.dumps({"read_num": source["read_num"],
                "boost_ratio": source["boost_ratio"], "account_read_base": source["account_read_base"]}), created_at=now()))
    return {"id": ident}


@router.get("/admin/products")
def admin_products(request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(*(products.c[key] for key in PUBLIC_COLUMNS), products.c.content,
            products.c.image_data.is_not(None).label("has_image"))
            .order_by(products.c.created_at.desc()).limit(200)).mappings().all()
    return [{**public(r), "content": r["content"], "has_image": r["has_image"]} for r in rows]


@router.get("/admin/feedback")
def admin_feedback(request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(feedback).order_by(feedback.c.created_at.desc()).limit(200)).mappings().all()
    return [dict(row) for row in rows]


@router.put("/admin/products/{product_id}")
def edit_product(product_id: str, payload: Draft, request: Request):
    admin(request)
    with database.ENGINE.begin() as connection:
        result = connection.execute(update(products).where(products.c.id == product_id,
            products.c.status == "draft").values(title=payload.title, track=payload.track,
            preview=payload.preview, content=payload.content, price_points=payload.price_points))
        if not result.rowcount:
            raise HTTPException(409, "只能修改草稿")
    return {"ok": True}


@router.put("/admin/products/{product_id}/image")
async def upload_image(product_id: str, request: Request):
    admin(request)
    data = await request.body()
    if not 0 < len(data) <= 8 * 1024 * 1024:
        raise HTTPException(400, "图片不能超过 8 MB")
    import io
    from PIL import Image, ImageFilter, ImageOps
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > 24_000_000:
                raise ValueError("image dimensions exceed limit")
            image.verify()
            fmt = image.format
    except Exception as exc:
        raise HTTPException(400, "无效图片") from exc
    if fmt not in {"PNG", "JPEG", "WEBP"}:
        raise HTTPException(400, "仅支持 PNG、JPEG、WebP")
    try:
        with Image.open(io.BytesIO(data)) as image:
            preview = ImageOps.exif_transpose(image).convert("RGB")
            preview.thumbnail((160, 160))
            preview = preview.filter(ImageFilter.GaussianBlur(radius=8))
            buffer = io.BytesIO()
            preview.save(buffer, format="JPEG", quality=65)
    except Exception as exc:
        raise HTTPException(400, "图片无法生成预览") from exc
    with database.ENGINE.begin() as connection:
        changed = connection.execute(update(products).where(products.c.id == product_id,
            products.c.status == "draft", products.c.product_type == "image").values(
                image_data=data, image_type={"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt],
                preview_image=buffer.getvalue()))
        if not changed.rowcount:
            raise HTTPException(409, "只能为图片草稿上传图片")
    return {"ok": True}


@router.get("/admin/products/{product_id}/image")
def admin_image(product_id: str, request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        row = connection.execute(select(products.c.image_data, products.c.image_type).where(
            products.c.id == product_id)).first()
    if not row or not row.image_data:
        raise HTTPException(404, "图片不存在")
    return Response(row.image_data, media_type=row.image_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/admin/products/{product_id}/publish")
def publish(product_id: str, request: Request):
    admin(request)
    with database.ENGINE.connect() as connection:
        candidate = connection.execute(select(products.c.content, products.c.product_type).where(products.c.id == product_id)).mappings().first()
    if not candidate:
        raise HTTPException(404, '商品不存在')
    if candidate and candidate['product_type'] == 'article':
        article = candidate['content'].strip()
        count = len(re.sub(r'\s+', '', article))
        if not 1000 <= count <= 1200:
            raise HTTPException(400, f'文章字数须为1000至1200字（不计空白），当前 {count} 字')
        key = os.getenv('MAKERS_MODELS_KEY', '').strip()
        if not key:
            raise HTTPException(503, '朱雀检测未配置，暂不能上架文章')
        try:
            response = requests.post('https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify',
                headers={'Authorization': 'Bearer ' + key}, json={'text': article, 'is_merge': True}, timeout=45)
            response.raise_for_status()
            result = response.json()
            human = float(result['labels_ratio']['0'])
            if result.get('status') != 'success' or not 0 <= human <= 1:
                raise ValueError('invalid detector result')
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(503, '朱雀检测失败，请稍后重试') from exc
        if human < 0.8:
            raise HTTPException(400, f'朱雀人工内容占比 {human * 100:.1f}%，需达到80%')
    try:
        with database.ENGINE.begin() as connection:
            row = connection.execute(select(products).where(products.c.id == product_id).with_for_update()).mappings().first()
            if not row or row["status"] != "draft" or not row["source_url"] or not row["source_title"]:
                raise HTTPException(409, "商品或来源不完整")
            if row['product_type'] != candidate['product_type'] or (row['product_type'] == 'article' and row['content'].strip() != article):
                raise HTTPException(409, '文章已修改，请重新检测')
            if connection.execute(select(jobs.c.id).where(jobs.c.product_id == product_id,
                    jobs.c.status.in_(["queued", "running"]))).first():
                raise HTTPException(409, "生成任务尚未完成")
            if not row["content"].strip() or (row["product_type"] == "image" and not row["image_data"]):
                raise HTTPException(400, "请先填写完整内容并检查图片")
            data = (row["image_data"] if row["product_type"] == "image" else
                    re.sub(r"\s+", "", row["content"]).encode("utf-8"))
            fingerprint = hashlib.sha256(row["product_type"].encode("ascii") + b'\0' + data).hexdigest()
            connection.execute(update(products).where(products.c.id == product_id).values(
                status="published", published_at=now(), content_fingerprint=fingerprint))
    except IntegrityError as exc:
        raise HTTPException(409, "相同成品已上架或售出，不能重复上架") from exc
    return {"ok": True}


@router.post("/admin/products/{product_id}/hide")
def hide(product_id: str, request: Request):
    admin(request)
    with database.ENGINE.begin() as connection:
        result = connection.execute(update(products).where(products.c.id == product_id,
            products.c.status == "published").values(status="hidden"))
        if not result.rowcount:
            raise HTTPException(409, "仅可下架未售出的商品")
    return {"ok": True}


@router.get("/products")
def list_products(request: Request):
    ready()
    user = getattr(request.state, "user", None)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(*(products.c[key] for key in PUBLIC_COLUMNS)).where(products.c.status.in_(["published", "sold"]))
            .order_by(products.c.published_at.desc()).limit(200)).mappings().all()
    return [public(r, user["id"] if user else None) for r in rows]


@router.get("/products/{product_id}/preview-image")
def preview_image(product_id: str):
    ready()
    with database.ENGINE.connect() as connection:
        data = connection.execute(select(products.c.preview_image).where(
            products.c.id == product_id, products.c.status.in_(["published", "sold"]))).scalar_one_or_none()
    if not data:
        raise HTTPException(404, "预览不存在")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.get("/my-purchases")
def mine(request: Request):
    ready()
    user = accounts.require_user(request)
    with database.ENGINE.connect() as connection:
        rows = connection.execute(select(*(products.c[key] for key in PUBLIC_COLUMNS)).where(products.c.buyer_id == user["id"])).mappings().all()
    return [public(r, user["id"]) for r in rows]


@router.post("/products/{product_id}/purchase")
def buy(product_id: str, request: Request):
    ready()
    user = accounts.require_user(request)
    try:
        return purchase(database.ENGINE, product_id, user["id"])
    except InsufficientPoints as exc:
        raise HTTPException(402, str(exc)) from exc
    except (SoldOut, PurchaseError) as exc:
        raise HTTPException(409, str(exc)) from exc


def owned(product_id, request, *, include_image=False):
    ready()
    user = accounts.require_user(request)
    with database.ENGINE.connect() as connection:
        image_column = products.c.image_data if include_image else products.c.image_data.is_not(None).label("has_image")
        row = connection.execute(select(products.c.title, products.c.content, products.c.image_type, image_column).where(products.c.id == product_id,
            products.c.buyer_id == user["id"])).mappings().first()
    if not row:
        raise HTTPException(404, "未找到已购买内容")
    return row, user


@router.get("/products/{product_id}/content")
def content(product_id: str, request: Request, response: Response):
    row, _ = owned(product_id, request)
    response.headers["Cache-Control"] = "private, no-store"
    return {"title": row["title"], "content": row["content"], "has_image": row["has_image"]}


@router.get("/products/{product_id}/image")
def image(product_id: str, request: Request):
    row, _ = owned(product_id, request, include_image=True)
    if not row["image_data"]:
        raise HTTPException(404, "图片不存在")
    return Response(row["image_data"], media_type=row["image_type"], headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/products/{product_id}/feedback")
def submit_feedback(product_id: str, payload: Feedback, request: Request):
    _, user = owned(product_id, request)
    with database.ENGINE.begin() as connection:
        connection.execute(feedback.insert().values(id=uuid.uuid4().hex, product_id=product_id,
            user_id=user["id"], body=payload.body, created_at=now()))
    return {"ok": True}
