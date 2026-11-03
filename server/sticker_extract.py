import html
import io
import re
import shutil
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

router = APIRouter()
ROOT = Path(__file__).resolve().parents[1] / 'output' / 'sticker-extract'
TTL = 6 * 3600
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36', 'Referer': 'https://mp.weixin.qq.com/'}

class ExtractRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)

def _objects(source):
    # Only split top-level list objects; nested watermark fields are excluded.
    depth = 0
    quote = None
    escaped = False
    start = None
    for i, c in enumerate(source):
        if quote:
            if escaped: escaped = False
            elif c == '\\': escaped = True
            elif c == quote: quote = None
            continue
        if c in "'\"": quote = c
        elif c == '{':
            if depth == 0: start = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start is not None:
                yield source[start:i + 1]
                start = None
        elif c == ']' and depth == 0:
            break

def parse_images(source):
    m = re.search(r'picture_page_info_list\s*[:=]\s*\[', source)
    urls = []
    if m:
        for obj in _objects(source[m.end():]):
            hit = re.search(r"cdn_url\s*:\s*(?:JsDecode\(\s*)?['\"]([^'\"]+)['\"]", obj)
            if hit:
                value = re.sub(r'\\x([0-9a-fA-F]{2})', lambda x: chr(int(x.group(1), 16)), hit.group(1))
                urls.append(html.unescape(value))
    else:
        soup = BeautifulSoup(source, 'html.parser')
        body = soup.find(id='js_content')
        if body:
            urls = [img.get('data-src') or img.get('src') for img in body.find_all('img')]
    result = []
    for value in urls:
        p = urlparse(value or '')
        if p.scheme in ('https', 'http') and p.hostname == 'mmbiz.qpic.cn':
            result.append(value)
    if len(result) > 30:
        raise ValueError('文章图片超过 30 张，暂无法完整提取')
    return result

def _dir(request, token):
    if not re.fullmatch(r'[0-9a-f]{32}', token): raise HTTPException(404, '结果不存在')
    path = ROOT / str(request.state.user['id']) / token
    if not path.is_dir() or time.time() - path.stat().st_mtime > TTL: raise HTTPException(404, '提取结果已过期，请重新提取')
    return path

@router.post('/api/sticker-extract')
def extract(payload: ExtractRequest, request: Request):
    match = re.search(r'https://mp\.weixin\.qq\.com/s(?:/[^\s<>"\']+|\?[^\s<>"\']+)', payload.url)
    if not match: raise HTTPException(400, '请粘贴完整的公众号文章链接')
    url = match.group(0).rstrip('，。；、）)】')
    try:
        # curl_cffi is optional; the normal client is the fallback.
        try:
            from curl_cffi import requests as browser_requests
            response = browser_requests.get(url, headers=HEADERS, impersonate='chrome', timeout=25, allow_redirects=False)
        except ImportError:
            response = requests.get(url, headers=HEADERS, timeout=25, allow_redirects=False)
        if response.status_code != 200: raise ValueError('文章暂时无法访问，请稍后重试')
        source = response.text
        urls = parse_images(source)
        if not urls:
            raise ValueError('没有识别到图片，文章可能需要微信验证或暂不支持该格式')
        title_node = BeautifulSoup(source, 'html.parser').find('meta', property='og:title')
        title = (title_node.get('content', '') if title_node else '')[:160]
        files = []
        total_bytes = 0
        for image_url in urls:
            # No redirects: never follow a CDN response to an arbitrary host.
            with requests.get(image_url, headers=HEADERS, timeout=(5, 30), stream=True, allow_redirects=False) as img:
                if img.status_code != 200: raise ValueError('图片下载失败，请稍后重试')
                buf = bytearray()
                for chunk in img.iter_content(65536):
                    buf.extend(chunk)
                    if len(buf) > 30 * 1024 * 1024: raise ValueError('图片过大，暂无法提取')
                data = bytes(buf)
                total_bytes += len(data)
                if total_bytes > 100 * 1024 * 1024: raise ValueError('图片总大小超过 100MB，暂无法提取')
                with Image.open(io.BytesIO(data)) as check:
                    fmt = check.format
                    check.verify()
                ext = {'JPEG':'jpg', 'PNG':'png', 'WEBP':'webp', 'GIF':'gif'}.get(fmt)
                if not ext: raise ValueError('图片格式暂不支持')
                files.append((data, ext))
        user_root = ROOT / str(request.state.user['id'])
        if user_root.exists():
            for old in user_root.iterdir():
                if old.is_dir() and time.time() - old.stat().st_mtime > TTL:
                    shutil.rmtree(old, ignore_errors=True)
        folder = user_root / uuid.uuid4().hex
        folder.mkdir(parents=True, exist_ok=False)
        for i, (data, ext) in enumerate(files, 1): (folder / f'{i:02d}.{ext}').write_bytes(data)
        return {'title': title, 'token': folder.name, 'images': [{'index': i, 'url': f'/api/sticker-extract/{folder.name}/{i}'} for i in range(1, len(files)+1)]}
    except HTTPException: raise
    except Exception as exc:
        raise HTTPException(502, str(exc) if isinstance(exc, ValueError) else '提取失败，请稍后重试') from exc

@router.get('/api/sticker-extract/{token}/zip')
def download_zip(token: str, request: Request):
    folder = _dir(request, token)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.iterdir()):
            if path.is_file(): archive.write(path, path.name)
    return Response(output.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="sticker-images.zip"'})

@router.get('/api/sticker-extract/{token}/{index}')
def image(token: str, index: int, request: Request, download: bool = False):
    folder = _dir(request, token)
    files = list(folder.glob(f'{index:02d}.*')) if 1 <= index <= 30 else []
    if not files: raise HTTPException(404, '图片不存在')
    return FileResponse(files[0], filename=files[0].name if download else None, content_disposition_type='attachment' if download else 'inline')
