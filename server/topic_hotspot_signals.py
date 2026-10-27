"""Bounded, read-only use of cached domestic hotspot-square signals."""
import json
import re
from datetime import datetime, timedelta, timezone

from . import hotspots, workbench_research

DOMESTIC = ('weibo', 'zhihu', 'douyin', 'toutiao', 'baidu', 'bilibili',
            'juejin', 'tieba', 'douban', 'v2ex')


def cached_topic_signals(topic: str, limit: int = 20) -> dict:
    tokens = workbench_research._tokens([topic])
    if not tokens:
        return {'status': 'no_keywords', 'items': []}
    client = hotspots._redis()
    if client is None:
        return {'status': 'unavailable', 'items': []}
    now = datetime.now(timezone.utc)
    matches, available = [], []
    for platform in DOMESTIC:
        try:
            key = hotspots.KEY_ITEMS.format(platform=platform)
            raw = client.get(key)
            ttl = client.ttl(key)
            if not raw or ttl is None or ttl <= 0 or ttl > hotspots.CACHE_TTL:
                continue
            entries = json.loads(raw)
            if not isinstance(entries, list):
                continue
            available.append(platform)
            observed = (now - timedelta(seconds=hotspots.CACHE_TTL - ttl)).isoformat()
            for item in entries:
                if not isinstance(item, dict) or item.get('platform') != platform:
                    continue
                title = str(item.get('title') or '').strip()[:300]
                url = str(item.get('url') or '').strip()
                if not title or not url.startswith('https://'):
                    continue
                haystack = (title + ' ' + str(item.get('excerpt') or '')[:200]).lower()
                hits = sum(1 for token in tokens if (bool(re.search(r'(?<![a-z0-9])' + re.escape(token) + r'(?![a-z0-9])', haystack))
                           if token.isascii() else token in haystack))
                if hits < min(2, len(tokens)):
                    continue
                matches.append({'title': title, 'url': url, 'platform': platform,
                                'platform_zh': hotspots.NAMES.get(platform, platform),
                                'rank': item.get('rank'), 'observed_at': observed,
                                'match_tokens': hits, 'source': 'hotspot_square_cache'})
        except (TypeError, ValueError, KeyError, ConnectionError):
            continue
        except Exception:
            # Redis may disappear during a request; preserve the original path.
            break
    matches.sort(key=lambda x: (-x['match_tokens'], x['rank'] if isinstance(x['rank'], int) else 999))
    return {'status': 'matched' if matches else ('no_match' if available else 'unavailable'),
            'available_platforms': available, 'items': matches[:max(0, min(limit, 20))]}
