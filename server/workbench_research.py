"""Public RSS search evidence. Search snippets are never verified facts."""
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


def search(query, fetch=False):
    endpoints = [('bing', 'https://www.bing.com/search', {'q':query,'format':'rss'}),
                 ('google-news', 'https://news.google.com/rss/search', {'q':query,'hl':'zh-CN','gl':'CN','ceid':'CN:zh-Hans'})]
    def run(spec):
        name, url, params = spec
        try:
            response = requests.get(url, params=params, timeout=18)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            entries = []
            for item in root.findall('.//item')[:5]:
                link = item.findtext('link') or ''
                if not link.startswith('https://'):
                    continue
                entries.append({'title':item.findtext('title') or '', 'url':link,
                    'excerpt':item.findtext('description') or '', 'published_at':item.findtext('pubDate') or '',
                    'provider':name, 'verification':'search_excerpt_only'})
            return {'provider':name, 'status':'ok' if entries else 'empty', 'entries':entries}
        except (requests.RequestException, ET.ParseError):
            return {'provider':name, 'status':'unavailable', 'entries':[]}
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(run, endpoints))
    sources = list({s['url']:s for run in runs for s in run['entries']}.values())
    if fetch:
        with ThreadPoolExecutor(max_workers=3) as pool:
            sources = list(pool.map(fetch_source,sources[:5]))
    return {'query':query, 'checked_at':datetime.now(timezone.utc).isoformat(), 'runs':runs,
            'sources':sources, 'status':'partial' if sources else 'unavailable',
            'limitations':'搜索摘要不是全文核验；未经原文验证的数据、案例不能当作已证实事实。'}


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
