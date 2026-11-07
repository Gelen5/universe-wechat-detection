"""Conservative, read-only candidate discovery from existing snapshots.

Topic-library matches are inspiration only, never evidence of reach.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
import re
from urllib.parse import urlparse

from sqlalchemy import select

from .models import HotspotSnapshot, ImageBoardItem, LowfansArticle
from .topic_library import collection


def _grams(text):
    clean = re.sub(r'[^\w\u4e00-\u9fff]', '', (text or '').casefold())
    return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}


def match_topics(title, track='', limit=5):
    query = _grams(title)
    if not query:
        return []
    rows, _ = collection()
    matches = []
    for idx, row in enumerate(rows):
        grams = _grams(row.get('title', ''))
        common = len(query & grams)
        if common < 2:
            continue
        similarity = 2 * common / (len(query) + len(grams))
        if track and track in (row.get('track'), row.get('category')):
            similarity = min(1.0, similarity + 0.05)
        if similarity >= 0.15:
            matches.append({'id': idx, 'title': row['title'], 'track': row.get('track', ''),
                            'score': round(similarity, 4), 'limitation': '历史选题无传播数据'})
    return sorted(matches, key=lambda x: (-x['score'], x['id']))[:max(0, min(limit, 20))]


def build_candidates(session, *, as_of=None, max_age_days=7, limit=50):
    if max_age_days <= 0:
        raise ValueError('max_age_days must be positive')
    now = as_of or datetime.now(timezone.utc)
    snapshots = session.execute(select(LowfansArticle).order_by(
        LowfansArticle.stat_date.desc(), LowfansArticle.rank_no.asc()).limit(5000)).scalars().all()
    latest = {}
    observations = {}
    for item in snapshots:
        if item.art_id:
            observations.setdefault(item.art_id, []).append({
                'observed_at': item.stat_date, 'read_num': item.read_num,
                'boost_ratio': item.boost_ratio, 'account_read_base': item.account_read_base})
        if item.art_id and item.art_id not in latest:
            latest[item.art_id] = item
    output = []
    for item in latest.values():
        try:
            date = datetime.fromisoformat(item.stat_date).replace(tzinfo=timezone.utc)
            age = (now - date).total_seconds() / 86400
            url = urlparse(item.art_url or '')
        except ValueError:
            continue
        if age < 0 or age > max_age_days or not item.title or url.scheme not in ('http', 'https') or not url.hostname:
            continue
        ratio = max(0.0, float(item.boost_ratio or 0))
        if not math.isfinite(ratio) or ratio <= 0 or int(item.account_read_base or 0) <= 0:
            continue
        # This is a ranking heuristic, not a probability; missing trend and
        # originality signals do not become fabricated scores.
        lowfans = min(30.0, 30 * math.log1p(ratio) / math.log1p(100))
        verified_100k = 25.0 if item.read_num >= 100000 else 0.0
        freshness = max(0.0, 10.0 * (1 - age / max_age_days))
        output.append({'topic': item.title, 'track': item.wx_type or '',
            'opportunity_score': round(lowfans + verified_100k + freshness, 2),
            'score_components': {'lowfans': round(lowfans, 2), 'verified_100k': verified_100k,
                                 'freshness': round(freshness, 2)},
            'source': {'id': item.art_id, 'title': item.title, 'url': item.art_url,
                       'observed_at': item.stat_date, 'read_num': item.read_num,
                       'read_display': '10万+' if item.read_num >= 100000 else str(item.read_num),
                       'boost_ratio': item.boost_ratio, 'account_read_base': item.account_read_base},
            'limitations': ['评分仅用于内部排序，不代表成功概率', '未核验原文内容及素材授权',
                            '热点增长和原创差异化尚未评分']})
    for candidate in output:
        candidate['observations'] = observations[candidate['source']['id']]
    return sorted(output, key=lambda x: (-x['opportunity_score'], x['source']['id']))[:max(0, min(limit, 200))]


def cluster_candidates(candidates):
    """Group exact normalized titles only; never merge distinct events heuristically."""
    groups = {}
    for candidate in candidates:
        normalized = re.sub(r'[^\w\u4e00-\u9fff]', '', candidate['topic'].casefold())
        if not normalized:
            continue
        key = (candidate.get('track') or '', normalized)
        groups.setdefault(key, []).append(candidate)
    result = []
    for entries in groups.values():
        ordered = sorted(entries, key=lambda x: (-x['opportunity_score'], x['source']['id']))
        result.append({'topic': ordered[0]['topic'], 'track': ordered[0]['track'],
                       'opportunity_score': ordered[0]['opportunity_score'],
                       'sources': [entry['source'] for entry in ordered],
                       'observations': {entry['source']['id']: entry['observations'] for entry in ordered},
                       'limitations': ordered[0]['limitations']})
    return sorted(result, key=lambda x: (-x['opportunity_score'], x['topic']))


def find_hotspots(session, title, *, as_of=None, hours=48, limit=5):
    """Match only exact normalized titles; no unsupported trend inference."""
    from datetime import timedelta
    now = as_of or datetime.now(timezone.utc)
    normalize = lambda x: re.sub(r'[^\w\u4e00-\u9fff]', '', (x or '').casefold())
    key = normalize(title)
    if not key:
        return []
    rows = session.execute(select(HotspotSnapshot).where(
        HotspotSnapshot.captured_at >= now - timedelta(hours=hours),
        HotspotSnapshot.captured_at <= now).order_by(HotspotSnapshot.captured_at.desc()).limit(3000)).scalars()
    return [{'platform': row.platform, 'title': row.title, 'rank': row.rank,
             'observed_at': row.captured_at.isoformat(), 'url': row.url}
            for row in rows if normalize(row.title) == key][:limit]


def classify_image_evidence(session, *, limit=100):
    """Do not label high-read images as low-fan without a matching baseline."""
    from .image_board import is_image_first, _lowfans_matches
    rows = session.execute(select(ImageBoardItem).order_by(
        ImageBoardItem.stat_date.desc(), ImageBoardItem.id.desc()).limit(1000)).scalars().all()
    unique = {}
    for row in rows:
        if row.sn and row.sn not in unique:
            unique[row.sn] = row
    matches = _lowfans_matches(session, list(unique))
    out = []
    for row in unique.values():
        match = matches.get(row.sn)
        image_first = is_image_first(row)
        is_lowfans = bool(match and match.get('account_read_base', 0) > 0 and match.get('boost_ratio', 0) > 0)
        out.append({'id': row.sn, 'title': row.title, 'track': row.wx_type or '', 'url': row.art_url, 'observed_at': row.stat_date,
                    'read_num': row.read_num, 'image_first': image_first,
                    'classification': 'verified_lowfans_image' if image_first and is_lowfans else
                        'ordinary_image' if image_first else 'not_image_first',
                    'lowfans_observation': match if is_lowfans else None})
    # Recent ordinary rows can fill a small result window before the matcher is
    # consulted, which hid every verified low-fan image behind them. Rank the
    # verified evidence first, then bound the response.
    priority = {'verified_lowfans_image': 0, 'ordinary_image': 1, 'not_image_first': 2}
    out.sort(key=lambda item: (priority[item['classification']], -(item['read_num'] or 0),
                               item['observed_at'] or '', item['id']))
    return out[:max(0, min(limit, 200))]
