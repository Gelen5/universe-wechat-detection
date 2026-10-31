"""抖音内容提取：把一个作品链接还原成可用的图文/视频素材。

为什么服务端做：抖音的作品数据不在页面 HTML 里，网页端是靠带签名的
``/aweme/v1/web/aweme/detail/`` 接口取回来的。签名有两层（``a_bogus`` 和
``x-secsdk-web-signature``），算法在 :mod:`server.douyin_signing` 里，是纯函数，
不需要浏览器。所以这里是一件很轻的事：算签名、发一个 GET、把结果整理成本站
自己的结构。

为什么不部署整套采集系统：抖音解析的常见方案是 Douyin_TikTok_Download_API
那类项目，它们带 PostgreSQL、Redis、任务队列和一个 Chromium 容器，官方标称
8 GB 内存 —— 其中浏览器容器一项实测常驻就有 2.5 GB。本站的服务器只有 1.6 GB，
同时还要跑工作台本身。签名既然能用一次 sm3 和一次 md5 算出来，就没有必要为了
它多养一台浏览器。

三条必须守住的边界：

1. **能取到的只有公开数据。** 标题、正文、标签、作者、互动数、图片/视频地址
   都是任何访客都能看到的公开内容。不碰私信、不碰需要登录才可见的作品。
2. **凭据必须由部署方提供。** 抖音在签名里校验访客 ID，所以这里需要一份
   ``DOUYIN_COOKIE``（至少含 ``UIFID``/``ttwid``）。缺了它不会静默返回空数据，
   而是明确报「凭据未配置」，避免把配置问题伪装成「这条作品没有内容」。
3. **视频不落内存。** 一条中长视频几十 MB，本站内存只有 1.6 GB，所以视频一律
   边收边转（``stream=True``），只有图片会缓存到磁盘。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from .douyin_signing import ABogus, encode_pairs, pick_uifid, websign

logger = logging.getLogger(__name__)

router = APIRouter()

# 这个 UA 会被 a_bogus 哈希进签名，所以「算签名用的 UA」和「发请求用的 UA」
# 必须是同一个字符串。改一处就必须改另一处，否则抖音判签名无效。
BROWSER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
MOBILE_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)

DETAIL_API = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

# 抖音网页端自己的请求参数。少几个不会立刻失败，但这些是它自己的页面会带的，
# 带着更像它自己的页面 —— 整套签名的意义就在这里。
BASE_PARAMS: dict[str, str] = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "pc_client_type": "1",
    "version_code": "290100",
    "version_name": "29.1.0",
    "cookie_enabled": "true",
    "screen_width": "1920",
    "screen_height": "1080",
    "browser_language": "zh-CN",
    "browser_platform": "Win32",
    "browser_name": "Chrome",
    "browser_version": "146.0.0.0",
    "browser_online": "true",
    "engine_name": "Blink",
    "engine_version": "146.0.0.0",
    "os_name": "Windows",
    "os_version": "10",
    "cpu_core_num": "8",
    "device_memory": "8",
    "platform": "PC",
    "downlink": "10",
    "effective_type": "4g",
    "round_trip_time": "0",
}

AWEME_IN_PATH = re.compile(r"/(?:video|note|share/video|share/note|slides)/(\d{15,25})")
SHORT_LINK = re.compile(r"(?:https?://)?v\.douyin\.com/[A-Za-z0-9_\-]+")
ANY_URL = re.compile(r"https?://[^\s\"'<>，。；！？、【】《》]+")
BARE_ID = re.compile(r"(?<!\d)(7\d{17,23})(?!\d)")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

BEIJING = timezone(timedelta(hours=8))

# ---------------------------------------------------------------- 媒体缓存
# 抖音图床地址带签名有效期（x-expires），转手给浏览器的方式注定会裂图：用户
# 看到结果时签名往往已经过期。所以提取时就把图片字节落盘，之后一律由本地文件
# 响应。视频相反：体积太大，一律边收边转，不进缓存。
MEDIA_TTL = max(60, int(os.getenv("DOUYIN_MEDIA_TTL", "21600")))            # 6 小时
MEDIA_MAX_BYTES = max(4, int(os.getenv("DOUYIN_MEDIA_MAX_MB", "512"))) * 1024 * 1024
MEDIA_BUDGET = max(1, int(os.getenv("DOUYIN_MEDIA_BUDGET_MB", "1024"))) * 1024 * 1024
_cache_lock = threading.Lock()

#: 只允许转发抖音自己的媒体域名，防止这个端点被当成任意 URL 的代理。
MEDIA_HOST_SUFFIXES = (
    "douyinpic.com",
    "douyinvod.com",
    "douyinstatic.com",
    "byteimg.com",
    "zjcdn.com",
    "douyin.com",
    "iesdouyin.com",
)


def cache_root() -> Path:
    """和 AI 超市/作品输出一样落在持久卷上，容器重建后仍在。"""
    configured = os.getenv("DOUYIN_MEDIA_DIR", "").strip()
    base = Path(configured) if configured else Path("/app/output/douyin-media")
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except OSError:
        fallback = Path(__file__).resolve().parents[1] / "output" / "douyin-media"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def media_key(url: str) -> str:
    """稳定标识：丢掉查询串里的签名，同一张图每次提取都落到同一个 key。"""
    parsed = urlparse(url)
    material = f"{(parsed.hostname or '').lower()}{parsed.path}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:40]


def _entry_paths(key: str) -> tuple[Path, Path]:
    root = cache_root()
    return root / f"{key}.bin", root / f"{key}.meta.json"


def cached_media(key: str) -> tuple[Path, dict[str, Any]] | None:
    """返回 (文件, 元数据)；过期或缺失都当未命中。"""
    blob, meta_path = _entry_paths(key)
    if not blob.is_file() or not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        stored_at = float(meta.get("stored_at", 0))
    except (OSError, ValueError):
        return None
    if time.time() - stored_at > MEDIA_TTL:
        return None
    return blob, meta


def store_media(key: str, payload: bytes, content_type: str, url: str) -> None:
    """原子写入：先写临时文件再改名，读方永远看不到半个文件。"""
    if len(payload) > MEDIA_MAX_BYTES:
        logger.info("douyin.media.cache_skip key=%s bytes=%s too_large", key, len(payload))
        return
    blob, meta_path = _entry_paths(key)
    suffix = os.getpid()
    tmp_blob = blob.with_name(f"{blob.name}.{suffix}.tmp")
    tmp_meta = meta_path.with_name(f"{meta_path.name}.{suffix}.tmp")
    try:
        tmp_blob.write_bytes(payload)
        tmp_meta.write_text(json.dumps({
            "stored_at": time.time(), "content_type": content_type, "url": url,
            "bytes": len(payload),
        }, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp_blob, blob)
        os.replace(tmp_meta, meta_path)
    except OSError as error:
        logger.warning("douyin.media.cache_write_failed key=%s error=%s", key, type(error).__name__)
        for path in (tmp_blob, tmp_meta):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def prune_cache() -> None:
    """超出预算就按最后使用时间删最旧的。磁盘只剩十几 GB，这个上限不能省。"""
    root = cache_root()
    try:
        entries = []
        total = 0
        for blob in root.glob("*.bin"):
            try:
                stat = blob.stat()
            except OSError:
                continue
            total += stat.st_size
            entries.append((stat.st_mtime, stat.st_size, blob))
        if total <= MEDIA_BUDGET:
            return
        entries.sort()
        for _mtime, size, blob in entries:
            if total <= MEDIA_BUDGET:
                break
            try:
                blob.unlink(missing_ok=True)
                blob.with_name(f"{blob.stem}.meta.json").unlink(missing_ok=True)
                total -= size
            except OSError:
                continue
        logger.info("douyin.media.pruned remaining_bytes=%s", total)
    except OSError:
        return


def warm_media_async(urls: list[str]) -> None:
    """预热放到后台线程：不要让用户等下载。图片签名会过期，必须提前落盘。"""
    if not urls:
        return

    def run() -> None:
        with _cache_lock:
            for url in urls:
                key = media_key(url)
                if cached_media(key):
                    continue
                try:
                    response = requests.get(
                        url,
                        headers={"User-Agent": BROWSER_AGENT, "Referer": "https://www.douyin.com/"},
                        timeout=25,
                    )
                except requests.RequestException as error:
                    logger.info("douyin.media.warm_skip key=%s error=%s", key, type(error).__name__)
                    continue
                if response.status_code >= 400:
                    logger.info("douyin.media.warm_skip key=%s status=%s", key, response.status_code)
                    continue
                content_type = response.headers.get("content-type", "application/octet-stream")
                if not content_type.startswith("image/"):
                    continue
                store_media(key, response.content, content_type, url)
            prune_cache()

    threading.Thread(target=run, name="douyin-warm", daemon=True).start()


# ---------------------------------------------------------------- 凭据
class MissingCredential(RuntimeError):
    """没有可用 Cookie。单独一个异常类型，避免和「这条作品没有内容」混在一起。"""


def _cookie() -> str:
    """部署方提供的 Cookie。环境变量优先，其次文件（便于挂载密钥卷）。"""
    raw = (os.getenv("DOUYIN_COOKIE", "") or "").strip()
    if not raw:
        path = (os.getenv("DOUYIN_COOKIE_FILE", "") or "").strip()
        if path:
            try:
                raw = Path(path).read_text(encoding="utf-8").strip()
            except OSError as error:
                logger.warning("douyin.cookie.read_failed path=%s error=%s", path, type(error).__name__)
                raw = ""
    if raw.startswith("{"):
        # 允许直接贴 douyin skill 那种 {"cookie": "..."} 的 JSON。
        try:
            raw = (json.loads(raw) or {}).get("cookie", "") or ""
        except ValueError:
            raw = ""
    if not raw:
        raise MissingCredential("DOUYIN_COOKIE 未配置")
    return raw


def _cookie_jar(raw: str) -> dict[str, str]:
    jar: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        jar[name.strip()] = value.strip()
    return jar


def _credential_error(error: MissingCredential) -> HTTPException:
    logger.warning("douyin.credential.missing detail=%s", error)
    return HTTPException(503, (
        "抖音解析凭据未配置或已失效（签名必须带上 Cookie 里的访客 ID）。"
        "请在服务器 .env 里配置 DOUYIN_COOKIE 后重启 web 服务；"
        "配置方式见 .env.example 的 DOUYIN_COOKIE 一节"
    ))


# ---------------------------------------------------------------- 链接归一化
def normalize_link(raw: str) -> tuple[str, str]:
    """把用户粘贴的内容收敛成 (aweme_id, 规范链接)。

    用户会粘分享文案（带一堆说明文字）、短链、App 分享链接，或者只粘 ID。
    """
    text = (raw or "").strip()
    if not text:
        raise HTTPException(400, "请先粘贴抖音作品链接")

    # 1) 直接能从 URL 里看出 aweme_id
    for candidate in ANY_URL.findall(text):
        parsed = urlparse(candidate)
        if not parsed.netloc.endswith(("douyin.com", "iesdouyin.com")):
            continue
        match = AWEME_IN_PATH.search(parsed.path)
        if match:
            aweme_id = match.group(1)
            return aweme_id, f"https://www.douyin.com/video/{aweme_id}"

    # 2) 短链要跟一次重定向（v.douyin.com 是抖音的短链域名）
    short = SHORT_LINK.search(text)
    if short:
        link = short.group(0)
        if not link.startswith("http"):
            link = f"https://{link}"
        resolved = _resolve_short_link(link)
        if resolved:
            return resolved
        raise HTTPException(400, "短链解析失败，请在浏览器打开作品页后复制地址栏链接")

    # 3) 只粘了 ID
    bare = BARE_ID.search(text)
    if bare:
        aweme_id = bare.group(1)
        return aweme_id, f"https://www.douyin.com/video/{aweme_id}"

    raise HTTPException(400, "没有识别到抖音作品链接，请复制作品页地址栏的完整链接")


def _resolve_short_link(link: str) -> tuple[str, str] | None:
    try:
        response = requests.get(
            link,
            headers={"User-Agent": MOBILE_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
            timeout=12,
            allow_redirects=True,
        )
    except requests.RequestException as error:
        logger.info("douyin.short_link_failed url=%s error=%s", link, type(error).__name__)
        return None
    final = response.url or ""
    match = AWEME_IN_PATH.search(urlparse(final).path)
    if not match:
        logger.info("douyin.short_link_unresolved url=%s final=%s", link, final[:120])
        return None
    aweme_id = match.group(1)
    return aweme_id, f"https://www.douyin.com/video/{aweme_id}"


# ---------------------------------------------------------------- 签名请求
def _signed_request(aweme_id: str) -> dict[str, Any]:
    """取一条作品详情。签名、超时、风控错误都在这里收敛。

    签名的顺序不能反：``a_bogus`` 覆盖的是它之前的那段查询串，
    ``x-secsdk-web-signature`` 覆盖的是包含 ``a_bogus``、``uifid``、
    ``timestamp`` 的整个查询串。
    """
    try:
        raw_cookie = _cookie()
    except MissingCredential as error:
        raise _credential_error(error) from error
    jar = _cookie_jar(raw_cookie)

    params = dict(BASE_PARAMS)
    params["aweme_id"] = aweme_id
    params["msToken"] = ""

    bogus = ABogus(BROWSER_AGENT).get_value(encode_pairs(list(params.items())))
    pairs = list(params.items()) + [("a_bogus", bogus)]

    try:
        query, signature, sign_headers = websign(pairs, pick_uifid(jar) or "")
    except (TypeError, ValueError) as error:  # 签名算法本身出问题，不要让 500 裸奔
        logger.warning("douyin.sign_failed aweme_id=%s error=%s", aweme_id, type(error).__name__)
        raise HTTPException(502, "签名计算失败，请稍后重试") from error

    headers = {
        "User-Agent": BROWSER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.douyin.com/",
        "Cookie": raw_cookie,
        **sign_headers,
    }
    url = f"{DETAIL_API}?{query}"

    try:
        response = requests.get(url, headers=headers, timeout=25)
    except requests.Timeout as error:
        raise HTTPException(504, "抖音响应超时，请稍后重试") from error
    except requests.RequestException as error:
        raise HTTPException(502, "网络异常，暂时取不到这条作品") from error

    if response.status_code == 403:
        body = (response.text or "")[:200]
        logger.warning("douyin.detail.refused aweme_id=%s body=%s", aweme_id, body)
        if "ArgusSecurityPlugin" in body or "uifid" in body.lower():
            raise HTTPException(503, (
                "抖音拒了这次请求（风控）。通常是 Cookie 里的访客 ID 失效，"
                "或者服务器出口 IP 被限流；请先更新 DOUYIN_COOKIE 再重试"
            ))
        raise HTTPException(502, "抖音返回 403，请稍后重试")
    if response.status_code == 429:
        raise HTTPException(429, "抖音限流了，请过几分钟再试")
    if response.status_code >= 400:
        raise HTTPException(502, f"抖音返回 {response.status_code}，请稍后重试")

    try:
        payload = response.json()
    except ValueError as error:
        raise HTTPException(502, "抖音返回的不是 JSON，可能被风控拦截") from error

    detail = payload.get("aweme_detail")
    if not detail:
        reason = (payload.get("filter_detail") or {}).get("filter_reason") or ""
        logger.info("douyin.detail.empty aweme_id=%s reason=%s", aweme_id, reason)
        if reason in {"core_dep", "delete", "status_self_see", "status_deleted"}:
            raise HTTPException(422, "这条作品已被删除、设为私密或仅作者可见")
        raise HTTPException(422, "没读到作品数据，请确认链接能在浏览器里正常打开")
    return detail


# ---------------------------------------------------------------- 结果整理
def to_count(value: Any) -> int:
    """抖音一般直接给整数；给了 "1.2万" 这种写法也换算一下。"""
    if isinstance(value, bool):
        return -1
    if isinstance(value, int):
        return value
    text = str(value or "").strip().replace(",", "").replace("+", "")
    if not text:
        return -1
    for unit, scale in (("亿", 100_000_000), ("万", 10_000), ("w", 10_000), ("k", 1_000)):
        if text.lower().endswith(unit):
            try:
                return int(float(text[: -len(unit)]) * scale)
            except ValueError:
                return -1
    try:
        return int(float(text))
    except ValueError:
        return -1


def human_time(value: Any) -> str:
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    return datetime.fromtimestamp(stamp, BEIJING).strftime("%Y-%m-%d %H:%M")


def _clean(text: Any) -> str:
    return CONTROL.sub("", str(text or "")).strip()


def pick_video(detail: dict[str, Any]) -> dict[str, Any] | None:
    """挑一条播放地址。

    抖音会在 ``bit_rate`` 里给多档码率，默认给最好的那档 —— 用户要的是素材，
    不是能省流量的预览。
    """
    video = detail.get("video") or {}
    if not isinstance(video, dict):
        return None

    best_url = ""
    best_rate = 0
    for item in video.get("bit_rate") or []:
        if not isinstance(item, dict):
            continue
        urls = (item.get("play_addr") or {}).get("url_list") or []
        if not urls:
            continue
        if (item.get("bit_rate") or 0) >= best_rate:
            best_rate = item.get("bit_rate") or 0
            best_url = urls[0]

    if not best_url:
        urls = (video.get("play_addr") or {}).get("url_list") or []
        best_url = urls[0] if urls else ""
    if not best_url:
        return None

    cover = ""
    for key in ("cover", "origin_cover", "dynamic_cover"):
        node = video.get(key) or {}
        urls = node.get("url_list") if isinstance(node, dict) else None
        if urls:
            cover = urls[0]
            break

    return {
        "url": best_url.replace("http://", "https://", 1),
        "width": video.get("width"),
        "height": video.get("height"),
        "duration": video.get("duration"),
        "quality": f"{max(best_rate // 1000, 0)}kbps" if best_rate else "",
        "poster": cover,
    }


def pick_images(detail: dict[str, Any]) -> list[dict[str, Any]]:
    """图文作品的配图。每条给原图，并带上尺寸便于前端排版。"""
    result: list[dict[str, Any]] = []
    for item in detail.get("images") or []:
        if not isinstance(item, dict):
            continue
        urls = item.get("url_list") or []
        if not urls:
            continue
        result.append({
            "url": urls[0].replace("http://", "https://", 1),
            "width": item.get("width"),
            "height": item.get("height"),
        })
    return result


def build_note(detail: dict[str, Any], aweme_id: str, link: str) -> dict[str, Any]:
    images = pick_images(detail)
    video = pick_video(detail)
    # 抖音的「图文」作品 aweme_type 是 68 这类非 0 值，图片数组非空即图文。
    kind = "image" if images else "video"

    author = detail.get("author") or {}
    avatar = ""
    for key in ("avatar_thumb", "avatar_medium", "avatar_larger"):
        node = author.get(key) or {}
        urls = node.get("url_list") if isinstance(node, dict) else None
        if urls:
            avatar = urls[0]
            break

    stats = detail.get("statistics") or {}
    desc = _clean(detail.get("desc"))
    tags: list[str] = []
    for extra in detail.get("text_extra") or []:
        if isinstance(extra, dict) and extra.get("hashtag_name"):
            tags.append(f"#{extra['hashtag_name']}")
    if not tags and desc:
        tags = [f"#{tag}" for tag in re.findall(r"#([^\s#]{1,40})", desc)][:10]

    # 抖音没有「标题」字段，正文就是标题。给一个短标题方便列表展示，同时保留
    # 完整正文，前端两者都要用。
    title = desc.splitlines()[0][:120] if desc else ""

    return {
        "id": aweme_id,
        "link": link,
        "kind": kind,
        "title": title,
        "desc": desc,
        "tags": tags,
        "author": {
            "name": _clean(author.get("nickname")),
            "id": author.get("unique_id") or author.get("short_id") or "",
            # 抖音用的是 sec_uid，主页链接要用它才对。
            "sec_uid": author.get("sec_uid") or "",
            "avatar": avatar,
        },
        "stats": {
            "liked": to_count(stats.get("digg_count")),
            "comment": to_count(stats.get("comment_count")),
            "share": to_count(stats.get("share_count")),
            "collected": to_count(stats.get("collect_count")),
            "play": to_count(stats.get("play_count")),
        },
        "published": human_time(detail.get("create_time")),
        "images": images,
        "video": video,
        "cover": (video or {}).get("poster") if kind == "video" else None,
        "imageCount": len(images) if kind == "image" else 0,
        "duration": video.get("duration") if video else None,
    }


# ---------------------------------------------------------------- 路由
class ExtractRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


@router.post("/api/douyin/extract")
def api_extract(payload: ExtractRequest):
    """提取作品数据，并把图片字节存到本地缓存。

    只读公开信息。图片会落盘（不是正文搬运）—— 这是必要的：源站签名几十分钟
    就失效，不留一份就无法在用户点开时还出得来。
    """
    aweme_id, link = normalize_link(payload.url)
    detail = _signed_request(aweme_id)
    note = build_note(detail, aweme_id, link)
    warm_media_async([image["url"] for image in note["images"]])
    logger.info(
        "douyin.extract id=%s kind=%s images=%s", note["id"], note["kind"], note["imageCount"]
    )
    return {"status": "success", "note": note}


def _host_allowed(url: str, suffixes: tuple[str, ...]) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in {"http", "https"} and host.endswith(suffixes)


@router.get("/api/douyin/media")
def api_media(url: str = Query(min_length=8, max_length=2048)):
    """同源提供图片：有缓存读本地文件，没有才去上游取一次并存下来。

    只允许抖音自己的图床域名，防止这个端点被当成任意 URL 的代理。
    """
    if not _host_allowed(url, MEDIA_HOST_SUFFIXES):
        raise HTTPException(400, "只允许转发抖音媒体地址")

    key = media_key(url)
    hit = cached_media(key)
    if hit:
        blob, meta = hit
        try:
            os.utime(blob, None)
        except OSError:
            pass
        return FileResponse(
            blob,
            media_type=meta.get("content_type", "application/octet-stream"),
            headers={"Cache-Control": "private, max-age=86400"},
        )

    try:
        response = requests.get(
            url,
            headers={"User-Agent": BROWSER_AGENT, "Referer": "https://www.douyin.com/"},
            timeout=25,
        )
    except requests.RequestException as error:
        raise HTTPException(502, "媒体下载失败") from error
    if response.status_code >= 400:
        raise HTTPException(502, "媒体下载失败，地址可能已过期")
    content_type = response.headers.get("content-type", "application/octet-stream")
    if not content_type.startswith(("image/", "video/")):
        raise HTTPException(415, "上游返回的不是图片或视频")
    store_media(key, response.content, content_type, url)
    return StreamingResponse(
        iter([response.content]),
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


def _stream_video(url: str) -> Iterator[bytes]:
    """边收边转。视频不进内存也不进磁盘缓存：本站内存只有 1.6 GB。"""
    response = requests.get(
        url,
        headers={"User-Agent": BROWSER_AGENT, "Referer": "https://www.douyin.com/"},
        timeout=60,
        stream=True,
    )
    try:
        response.raise_for_status()
        for chunk in response.iter_content(chunk_size=256 * 1024):
            if chunk:
                yield chunk
    finally:
        response.close()


@router.get("/api/douyin/video")
def api_video(id: str = Query(min_length=15, max_length=25, pattern=r"^\d+$")):
    """按 aweme_id 现取现转视频。

    为什么不直接给上游地址：抖音的播放地址带 ``x-expires``，通常几十分钟就
    失效，用户点开时多半已经 403。这里每次都重新取一次播放地址，代价只是一个
    签过名的 GET —— 比让用户看到「视频加载失败」便宜得多。
    """
    detail = _signed_request(id)
    video = pick_video(detail)
    if not video or not video.get("url"):
        raise HTTPException(404, "这条作品没有视频")
    if not _host_allowed(video["url"], MEDIA_HOST_SUFFIXES):
        raise HTTPException(502, "上游返回的播放地址不在允许的域名内")
    return StreamingResponse(
        _stream_video(video["url"]),
        media_type="video/mp4",
        headers={"Cache-Control": "private, no-store"},
    )
