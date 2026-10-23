"""Public RSS search evidence. Search snippets are never verified facts.

The topic stage needs real signals, not one keyword lookup: several targeted
queries (hot discussion, platform chatter, recent coverage, controversy) are
fanned out, results are deduped, and the top pages are actually fetched so the
model can read the article body instead of a 140-character snippet.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
import json
import xml.etree.ElementTree as ET
import requests
import ipaddress
import socket
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup


# Mirrors the query templates in the Skill's references/topic-selection.md:
# 热度看讨论量，相关度看平台，切入价值看争议。
QUERY_TEMPLATES = (
    "{topic} 热点 讨论",
    "{topic} 微博 知乎 热搜",
    "{topic} 最新 进展 报道",
    "{topic} 争议 观点 讨论",
)

ENDPOINTS = (
    ("bing", "https://www.bing.com/search", {"format": "rss"}),
    ("google-news", "https://news.google.com/rss/search",
     {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}),
)


def topic_queries(topic, limit: int = 3):
    """Turn one topic into several targeted queries (deduped, bounded)."""
    seed = str(topic or "").strip()
    if not seed:
        return []
    queries = []
    for template in QUERY_TEMPLATES:
        text = template.format(topic=seed)
        if text not in queries:
            queries.append(text)
        if len(queries) >= max(1, limit):
            break
    return queries


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Only public HTTPS sources are permitted')
    addresses = socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError('Private source address rejected')


def fetch_source(source):
    result = dict(source)
    url = source['url']
    try:
        for _ in range(4):
            public_url(url)
            with requests.get(url,timeout=(5,10),allow_redirects=False,stream=True) as response:
                if response.is_redirect:
                    url = urljoin(url,response.headers.get('Location',''))
                    continue
                response.raise_for_status()
                if 'text/html' not in response.headers.get('Content-Type',''):
                    raise ValueError('Source is not an HTML document')
                raw = bytearray()
                for chunk in response.iter_content(16384):
                    raw.extend(chunk)
                    if len(raw) > 1_000_000:
                        raise ValueError('Source exceeds size limit')
                soup = BeautifulSoup(bytes(raw),'html.parser')
                for node in soup.select('script,style,nav,header,footer'):
                    node.decompose()
                article = soup.find('article') or soup.find('main') or soup
                paragraphs = [p.get_text(' ',strip=True) for p in article.find_all('p')]
                text = '\n'.join(p for p in paragraphs if len(p)>25)[:6000]
                if len(text)<150:
                    raise ValueError('Insufficient source text')
                result.update(content=text, final_url=url, verification='page_fetched_not_fact_checked')
                return result
        raise ValueError('Too many redirects')
    except (ValueError,OSError,requests.RequestException):
        result['fetch_status'] = 'unavailable'
        return result


def _run_query(spec):
    name, url, base_params, query, timeout = spec
    params = dict(base_params)
    params["q"] = query
    try:
        response = requests.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        entries = []
        for item in root.findall('.//item')[:6]:
            link = item.findtext('link') or ''
            if not link.startswith('https://'):
                continue
            entries.append({'title': item.findtext('title') or '', 'url': link,
                            'excerpt': item.findtext('description') or '',
                            'published_at': item.findtext('pubDate') or '',
                            'provider': name, 'query': query,
                            'verification': 'search_excerpt_only'})
        return {'provider': name, 'query': query,
                'status': 'ok' if entries else 'empty', 'entries': entries}
    except Exception:  # best-effort fanout: any failure just means "no signal here"
        return {'provider': name, 'query': query, 'status': 'unavailable', 'entries': []}


def search(query, *, fetch: bool = False, queries=None, max_sources: int = 12,
           max_fetch: int = 3, timeout: int = 14):
    """Fan out over several queries, dedupe, and optionally fetch the top pages."""
    seeds = []
    for item in (queries if queries is not None else [query]):
        text = str(item or "").strip()
        if text and text not in seeds:
            seeds.append(text)
    specs = [(name, url, params, seed, timeout)
             for seed in seeds for name, url, params in ENDPOINTS]
    runs = []
    if specs:
        with ThreadPoolExecutor(max_workers=min(4, len(specs))) as pool:
            runs = list(pool.map(_run_query, specs))

    by_url = {}
    for run in runs:
        for entry in run['entries']:
            by_url.setdefault(entry['url'], entry)
    sources = list(by_url.values())[:max_sources]

    fetched = []
    if fetch and sources:
        with ThreadPoolExecutor(max_workers=3) as pool:
            fetched = list(pool.map(fetch_source, sources[:max_fetch]))

    with_content = [item for item in fetched if item.get('content')]
    status = 'complete' if with_content else ('partial' if sources else 'unavailable')
    return {'query': query, 'queries': seeds,
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'runs': runs, 'sources': sources, 'fetched': fetched,
            'fetched_count': len(with_content), 'status': status,
            'limitations': '搜索摘要与网页正文都不是事实核验；未经原文验证的数据、案例不能当作已证实事实。'}


def compact(research: dict, *, source_limit: int = 8, fetch_limit: int = 3,
            excerpt_chars: int = 700) -> dict:
    """Prompt-sized view: keep URLs and real excerpts, drop the raw feed noise."""
    return {
        'status': research.get('status'),
        'queries': research.get('queries') or [research.get('query')],
        'checked_at': research.get('checked_at'),
        'sources': [{key: source.get(key) for key in
                     ('title', 'url', 'provider', 'published_at', 'verification')}
                    for source in (research.get('sources') or [])[:source_limit]],
        'fetched': [{'url': item.get('final_url') or item.get('url'),
                     'title': item.get('title'),
                     'excerpt': (item.get('content') or '')[:excerpt_chars]}
                    for item in (research.get('fetched') or []) if item.get('content')][:fetch_limit],
        'limitations': research.get('limitations'),
    }


def history(root):
    path = root / 'history' / 'published.json'
    if not path.exists():
        return {'status':'unavailable', 'titles':[], 'note':'没有发布历史，无法证明历史不重复'}
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        rows = data if isinstance(data,list) else data.get('articles', data.get('published', []))
        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()[:10]
        titles = [str(row.get('title','')) for row in rows if str(row.get('date') or row.get('published_at') or '')[:10] >= cutoff]
        return {'status':'checked','titles':titles}
    except (ValueError, TypeError, AttributeError):
        return {'status':'unavailable','titles':[],'note':'发布历史无法解析，未完成去重'}


def duplicate(title, titles):
    return any(SequenceMatcher(None,title,old).ratio() > .6 for old in titles)
