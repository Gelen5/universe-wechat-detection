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
import re
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

SEARCH_ENDPOINTS = (
    ("bing", "https://www.bing.com/search", {"format": "rss"}),
    ("google-news", "https://news.google.com/rss/search",
     {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}),
)

# 检索型补强：搜狗微信能拿到公众号文章标题与最近发布时间（实测可用）。
# 百度资讯与知乎搜索在服务器上分别返回验证码页和 403，暂不接入（见 limitations）。
SOGOU_WEIXIN = ("sogou-weixin", "https://weixin.sogou.com/weixin", {"type": "2"})

# 行业动态：查询无关的最新条目，用来补时效性（每个源取最新几条）。
FEEDS = (
    ("tmtpost", "https://www.tmtpost.com/rss"),
    ("sina-tech", "https://rss.sina.com.cn/tech/rollnews.xml"),
    ("sspai", "https://sspai.com/feed"),
    ("infoq-cn", "https://www.infoq.cn/feed"),
    ("hnrss", "https://hnrss.org/frontpage"),
    ("techcrunch", "https://techcrunch.com/feed/"),
)

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"),
    "Accept-Language": "zh-CN,zh;q=0.9",
}


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


def _entry(name, title, url, excerpt, published, query, verification='search_excerpt_only'):
    return {'title': title.strip(), 'url': url, 'excerpt': (excerpt or '')[:400],
            'published_at': (published or '').strip(), 'provider': name, 'query': query,
            'verification': verification}


def _run_query(spec):
    name, url, base_params, query, timeout = spec
    params = dict(base_params)
    params["q"] = query
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        entries = []
        for item in root.findall('.//item')[:6]:
            link = _secure((item.findtext('link') or '').strip())
            if not link.startswith('https://'):
                continue
            entries.append(_entry(name, item.findtext('title') or '', link,
                                  item.findtext('description') or '',
                                  item.findtext('pubDate') or '', query))
        return {'provider': name, 'query': query,
                'status': 'ok' if entries else 'empty', 'entries': entries}
    except Exception:  # best-effort fanout: any failure just means "no signal here"
        return {'provider': name, 'query': query, 'status': 'unavailable', 'entries': []}


def _run_sogou(spec):
    """搜狗微信检索：只取标题/链接/时间，链接是搜狗跳转，仍标注为仅摘要。"""
    query, timeout = spec
    name = SOGOU_WEIXIN[0]
    params = dict(SOGOU_WEIXIN[2])
    params["query"] = query
    try:
        response = requests.get(SOGOU_WEIXIN[1], params=params, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        text = response.text
        if any(marker in text for marker in ("请输入验证码", "antispider", "安全验证")):
            raise ValueError("sogou blocked")
        soup = BeautifulSoup(text, "html.parser")
        entries = []
        for node in soup.select("h3 a[href*='/link?url=']")[:6]:
            title = node.get_text(" ", strip=True)
            if not title:
                continue
            href = urljoin("https://weixin.sogou.com", node.get("href", ""))
            entries.append(_entry(name, title, href, "", "", query))
        return {'provider': name, 'query': query,
                'status': 'ok' if entries else 'empty', 'entries': entries}
    except Exception:
        return {'provider': name, 'query': query, 'status': 'unavailable', 'entries': []}


def _run_feed(spec):
    """行业 RSS：与查询无关的最新条目，由调用方按关键词过滤。"""
    name, url, timeout = spec
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        entries = []
        for item in root.findall('.//item')[:12]:
            link = _secure((item.findtext('link') or '').strip())
            if not link.startswith('https://'):
                continue
            entries.append(_entry(name, item.findtext('title') or '', link,
                                  item.findtext('description') or '',
                                  item.findtext('pubDate') or '', '', 'feed_headline_only'))
        return {'provider': name, 'query': '', 'status': 'ok' if entries else 'empty',
                'entries': entries}
    except Exception:
        return {'provider': name, 'query': '', 'status': 'unavailable', 'entries': []}


STOP_TOKENS = {"热点", "讨论", "最新", "进展", "报道", "微博", "知乎", "热搜", "争议",
               "观点", "相关", "重点", "关注", "适合", "文章", "微信", "公众", "深度"}


def _tokens(seeds):
    """把查询句拆成可匹配的词：英文按词，中文按二元组（去停用词）。"""
    text = " ".join(seeds).lower()
    tokens = set(re.findall(r"[a-z0-9]{2,}", text))
    for block in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        for index in range(len(block) - 1):
            tokens.add(block[index:index + 2])
    return {token for token in tokens if token not in STOP_TOKENS}


TECH_HINTS = ("ai", "agi", "openai", "chatgpt", "gpt", "claude", "gemini", "llm", "agent",
              "anthropic", "deepmind", "人工智能", "大模型", "模型", "算法", "编程", "开发者",
              "程序员", "芯片", "算力", "开源", "智能体", "软件", "科技", "云计算", "gpu", "代码")


# 只有这几家是 AI/技术垂类，允许"和主题无关但属于科技动态"的条目
AI_FEEDS = {"infoq-cn", "techcrunch", "hnrss"}


def _hint_hit(haystack, hint):
    """英文提示词要按词边界匹配，否则 Alzheimer 里的 ai 也算命中。"""
    if hint.isascii():
        return re.search(rf"\b{re.escape(hint)}\b", haystack) is not None
    return hint in haystack


def _feed_relevance(entry, tokens, provider=""):
    """topic=和主题有词面交集；tech=垂类科技动态；None=八卦/财经/无关，直接丢掉。"""
    haystack = f"{entry.get('title', '')} {entry.get('excerpt', '')}".lower()
    if sum(1 for token in tokens if token in haystack) >= 2:
        return 'topic'
    if provider in AI_FEEDS and any(_hint_hit(haystack, hint) for hint in TECH_HINTS):
        return 'tech'
    return None


def _secure(url):
    """新浪等源的条目链接是 http，统一升到 https（安全校验只放行 https）。"""
    return url.replace("http://", "https://", 1) if url.startswith("http://") else url


def _norm(url):
    return url.split("#", 1)[0].rstrip("/")


def search(query, *, fetch: bool = False, queries=None, max_sources: int = 30,
           max_fetch: int = 3, timeout: int = 14):
    """Fan out over several queries, dedupe, and optionally fetch the top pages."""
    seeds = []
    for item in (queries if queries is not None else [query]):
        text = str(item or "").strip()
        if text and text not in seeds:
            seeds.append(text)

    query_specs = [(name, url, params, seed, timeout)
                   for seed in seeds for name, url, params in SEARCH_ENDPOINTS]
    sogou_specs = [(seed, timeout) for seed in seeds]
    feed_specs = [(name, url, timeout) for name, url in FEEDS]

    runs, feed_runs = [], []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_run_query, spec) for spec in query_specs]
        futures += [pool.submit(_run_sogou, spec) for spec in sogou_specs]
        feed_futures = [pool.submit(_run_feed, spec) for spec in feed_specs]
        runs = [future.result() for future in futures]
        feed_runs = [future.result() for future in feed_futures]

    tokens = _tokens(seeds)
    by_url = {}
    for run in runs:  # 检索结果优先，但同样要过主题相关性（Bing 对长查询会返回跑题结果）
        for entry in run['entries']:
            haystack = f"{entry.get('title', '')} {entry.get('excerpt', '')}".lower()
            if not any(token in haystack for token in tokens):
                continue
            by_url.setdefault(_norm(entry['url']), entry)
    for run in feed_runs:  # 行业 RSS：只留命中的，没命中就留最新一条保时效
        picked = []
        for entry in run['entries']:
            relevance = _feed_relevance(entry, tokens, run['provider'])
            if relevance:
                picked.append(dict(entry, relevance=relevance))
        for entry in picked[:2]:
            by_url.setdefault(_norm(entry['url']), entry)
    # 按来源轮转取前 N 条：否则检索结果会把行业 RSS 全挤掉，证据又只剩两三个源
    groups = {}
    for entry in by_url.values():
        groups.setdefault(entry["provider"], []).append(entry)
    preferred = [name for name, _, _ in SEARCH_ENDPOINTS] + [SOGOU_WEIXIN[0]] + [name for name, _ in FEEDS]
    order = [name for name in preferred if name in groups] + [name for name in groups if name not in preferred]
    sources, index = [], 0
    while len(sources) < max_sources and any(len(groups[name]) > index for name in order):
        for name in order:
            if len(sources) >= max_sources:
                break
            if len(groups[name]) > index:
                sources.append(groups[name][index])
        index += 1

    fetched = []
    if fetch and sources:
        # 搜狗是跳转链接，抓正文基本必失败；排到后面，先抓真实文章地址
        # 抓正文优先真实文章（行业 RSS），其次是新闻检索，搜狗跳转放最后
        # 抓正文的顺序：主题命中 > 科技媒体（正文质量稳定）> 新闻检索 > 其它 RSS > 搜狗跳转
        feed_names = {name for name, _ in FEEDS}
        tech_media = AI_FEEDS
        candidates = ([item for item in sources if item.get('relevance') == 'topic']
                      + [item for item in sources if item['provider'] in tech_media
                         and item.get('relevance') != 'topic']
                      + [item for item in sources if item['provider'] not in feed_names
                         and item['provider'] != SOGOU_WEIXIN[0]]
                      + [item for item in sources if item['provider'] in feed_names
                         and item['provider'] not in tech_media
                         and item.get('relevance') != 'topic']
                      + [item for item in sources if item['provider'] == SOGOU_WEIXIN[0]])
        with ThreadPoolExecutor(max_workers=3) as pool:
            fetched = list(pool.map(fetch_source, candidates[:max_fetch]))

    with_content = [item for item in fetched if item.get('content')]
    status = 'complete' if with_content else ('partial' if sources else 'unavailable')
    return {'query': query, 'queries': seeds,
            'checked_at': datetime.now(timezone.utc).isoformat(),
            'runs': runs + feed_runs, 'sources': sources, 'fetched': fetched,
            'fetched_count': len(with_content), 'status': status,
            'providers': sorted({source['provider'] for source in sources}),
            'limitations': ('搜索摘要与网页正文都不是事实核验；未经原文验证的数据、案例不能当作已证实事实。'
                            '百度资讯与知乎搜索在本服务器被反爬拦截，未接入。')}


def compact(research: dict, *, source_limit: int = 12, fetch_limit: int = 3,
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
