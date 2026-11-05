"""Account-scoped topic library, using the packaged local collection."""
from functools import lru_cache
import gzip
import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import MetaData, Table, Column, String, Integer, and_, delete, insert, select
from . import accounts, database, viral_insights_membership as membership

router = APIRouter()
metadata = MetaData()
favorites = Table('topic_library_favorites', metadata,
    Column('user_id', String(64), primary_key=True),
    Column('topic_id', Integer, primary_key=True))

def init_schema():
    metadata.create_all(database.ENGINE)

@lru_cache(maxsize=1)
def collection():
    with gzip.open(Path(__file__).parent / 'topic_library_data.json.gz', 'rt', encoding='utf-8') as stream:
        rows = json.load(stream)
    categories = {}
    for row in rows:
        tracks = categories.setdefault(row['category'], {})
        tracks[row['track']] = tracks.get(row['track'], 0) + 1
    return rows, categories

@router.get('/topic-library', include_in_schema=False)
def page():
    return FileResponse(Path(__file__).parent.parent / 'static' / 'index.html', headers={'Cache-Control': 'no-cache'})

@router.get('/topic-library-frame', include_in_schema=False)
def frame():
    return FileResponse(Path(__file__).parent.parent / 'static' / 'topic-library.html', headers={'Cache-Control': 'no-cache'})

@router.get('/api/topic-library/categories')
def get_categories(request: Request):
    _, categories = collection()
    return {'categories': [{'name': category, 'tracks': [{'name': track, 'count': count} for track, count in tracks.items()]} for category, tracks in categories.items()]}

@router.get('/api/topic-library')
def list_topics(request: Request, category: str = Query('', max_length=100), track: str = Query('', max_length=100), q: str = Query('', max_length=100), saved: bool = False, page: int = Query(1, ge=1, le=10000), page_size: int = Query(20, ge=1, le=50)):
    user = getattr(request.state, 'user', None)
    accessible = membership.has_access(user['id'] if user else None)
    rows, categories = collection()
    if not accessible:
        category = next(iter(categories))
        track = next(iter(categories[category]))
        q, saved, page, page_size = '', False, 1, membership.preview_limit()
    with database.ENGINE.connect() as conn:
        saved_ids = set(conn.execute(select(favorites.c.topic_id).where(favorites.c.user_id == user['id'])).scalars()) if user and accessible else set()
    needle = q.strip().casefold()
    selected = ((idx, row) for idx, row in enumerate(rows) if (not saved or idx in saved_ids) and (saved or bool(needle) or not category or row['category'] == category) and (saved or bool(needle) or not track or row['track'] == track) and (not needle or needle in (row['category'] + row['track'] + row['title']).casefold()))
    start = (page - 1) * page_size
    items, total = [], 0
    for idx, row in selected:
        if start <= total < start + page_size:
            items.append({'id': idx, **row, 'saved': idx in saved_ids})
        total += 1
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size, 'saved_count': len(saved_ids), 'preview': not accessible}

@router.put('/api/topic-library/favorites/{topic_id}')
def add_favorite(topic_id: int, request: Request):
    user = accounts.require_user(request)
    membership.require_access(request)
    rows, _ = collection()
    if topic_id < 0 or topic_id >= len(rows):
        raise HTTPException(404, '选题不存在')
    with database.ENGINE.begin() as conn:
        # Idempotent for repeat clicks; the composite primary key prevents duplicates.
        if not conn.execute(select(favorites.c.topic_id).where(and_(favorites.c.user_id == user['id'], favorites.c.topic_id == topic_id))).first():
            try:
                with conn.begin_nested():
                    conn.execute(insert(favorites).values(user_id=user['id'], topic_id=topic_id))
            except database.IntegrityError:
                pass
    return {'saved': True}

@router.delete('/api/topic-library/favorites/{topic_id}')
def remove_favorite(topic_id: int, request: Request):
    user = accounts.require_user(request)
    membership.require_access(request)
    with database.ENGINE.begin() as conn:
        conn.execute(delete(favorites).where(and_(favorites.c.user_id == user['id'], favorites.c.topic_id == topic_id)))
    return {'saved': False}
