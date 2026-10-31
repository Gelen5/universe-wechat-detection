"""小红书内容提取：把一个作品链接还原成可用的图文/视频素材。

为什么服务端做：小红书的作品页是「给浏览器看的」，数据藏在
``window.__INITIAL_STATE__`` 里。浏览器直接抓会被跨域和风控挡住，
所以这里由服务端取一次、解析成本站自己的结构再交给前端。

两条必须守住的边界：

1. **能取到的只有公开数据。** 标题、正文、标签、作者、互动数、图片/视频
   地址都是页面本来就会公开给任何访客的内容。不碰私信、不碰登录态、
   不碰需要权限才可见的作品。
2. **链接必须带 ``xsec_token``。** 实测：裸的
   ``/explore/<id>`` 会返回一个空壳页面（``noteDetailMap`` 为空），
   只有从站内复制出来、带 ``xsec_token`` 的链接才带数据。这是平台侧的
   限制，不是实现偷懒；接口据此给出明确的失败原因，而不是静默返回空白。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlparse

import requests
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

BROWSER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "user-agent": BROWSER_AGENT,
}
STATE_PATTERN = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", re.S)
NOTE_ID = re.compile(r"(?:explore|discovery/item|item)/([0-9a-zA-Z]{16,32})")
SHORT_LINK = re.compile(r"(?:https?://)?xhslink\.(?:com|cn)/[^\s\"<>\\^`{|}，。；！？、【】《》]+")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# 互动数在页面上是 "1.2万" / "10+" 这种给人看的写法，统一换算成整数。
COUNT_UNITS = (("亿", 100_000_000), ("w", 10_000), ("万", 10_000), ("k", 1_000))
BEIJING = timezone(timedelta(hours=8))


class ExtractRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


def normalize_link(raw: str) -> str:
    """把用户粘贴的内容收敛成一个带 token 的作品链接。

    用户会粘分享文案（带一堆说明文字）、短链、App 分享链接，
    这里只负责找到那个真正的作品地址。
    """
    text = (raw or "").strip()
    if not text:
        raise HTTPException(400, "请先粘贴小红书作品链接")
    if match := SHORT_LINK.search(text):
        resolved = _resolve_short_link(match.group())
        if resolved:
            return resolved
        raise HTTPException(400, "短链解析失败，请在浏览器打开作品页后复制地址栏链接")
    for candidate in re.findall(r"https?://[^\s\"'<>，。；！？、]+", text):
        parsed = urlparse(candidate)
        if parsed.netloc.endswith(("xiaohongshu.com", "rednote.com")) and NOTE_ID.search(parsed.path):
            return candidate
    # 允许只粘 ID
    if bare := NOTE_ID.search(text):
        return f"https://www.xiaohongshu.com/explore/{bare.group(1)}"
    if re.fullmatch(r"[0-9a-f]{16,32}", text):
        return f"https://www.xiaohongshu.com/explore/{text}"
    raise HTTPException(400, "没有识别到小红书作品链接，请复制作品页地址栏的完整链接")


def _resolve_short_link(short: str) -> str:
    url = short if short.startswith("http") else f"https://{short}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True, stream=True)
        response.close()
        return response.url if NOTE_ID.search(urlparse(response.url).path) else ""
    except requests.RequestException as error:
        logger.info("xhs.short_link_failed url=%s error=%s", url, type(error).__name__)
        return ""


def note_id_of(link: str) -> str:
    match = NOTE_ID.search(urlparse(link).path or link)
    return match.group(1) if match else ""


def to_count(value: Any) -> int:
    """把 "1.2万"、"999+"、12 统一成整数；无法判断时返回 -1。"""
    if isinstance(value, bool):
        return -1
    if isinstance(value, int):
        return value
    text = str(value or "").strip().replace(",", "").replace("+", "")
    if not text:
        return -1
    for unit, scale in COUNT_UNITS:
        if text.lower().endswith(unit):
            try:
                return int(float(text[: -len(unit)]) * scale)
            except ValueError:
                return -1
    try:
        return int(float(text))
    except ValueError:
        return -1


def parse_state(html: str) -> dict[str, Any]:
    match = STATE_PATTERN.search(html or "")
    if not match:
        return {}
    raw = (match.group(1).replace("new Map([])", "[]")
           .replace("new Set([])", "[]").replace(":undefined", ":null"))
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        return {}


def _pick_note(state: dict[str, Any]) -> dict[str, Any]:
    """兼容 PC 与手机两套结构，取第一份真正的作品数据。"""
    for detail in (state.get("note") or {}).get("noteDetailMap", {}).values():
        if isinstance(detail, dict) and isinstance(detail.get("note"), dict) and detail["note"]:
            return detail["note"]
    phone = ((state.get("noteData") or {}).get("data") or {}).get("noteData")
    return phone if isinstance(phone, dict) else {}


def extract_images(note: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in note.get("imageList") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("urlDefault") or item.get("url") or ""
        if not url:
            for info in item.get("infoList") or []:
                if isinstance(info, dict) and info.get("imageScene") == "WB_DFT" and info.get("url"):
                    url = info["url"]
                    break
        if not url:
            continue
        result.append({
            "url": url.replace("http://", "https://", 1),
            "width": item.get("width"),
            "height": item.get("height"),
            "live": bool(item.get("livePhoto")),
        })
    return result


def extract_video(note: dict[str, Any]) -> dict[str, Any] | None:
    media = (note.get("video") or {}).get("media") or {}
    streams = media.get("stream") or {}
    candidates: list[dict[str, Any]] = []
    for items in streams.values():
        for stream in items or []:
            if isinstance(stream, dict) and stream.get("masterUrl"):
                candidates.append(stream)
    if not candidates:
        return None
    # 优先高码率；同一作品里清晰度差异明显，默认给最好的那份。
    best = max(candidates, key=lambda s: (s.get("size") or 0, s.get("width") or 0))
    poster = ""
    image = (note.get("video") or {}).get("image") or {}
    if isinstance(image, dict):
        poster = image.get("firstFrame") or image.get("thumbnailFileid") or ""
    return {
        "url": (best.get("masterUrl") or "").replace("http://", "https://", 1),
        "width": best.get("width"),
        "height": best.get("height"),
        "duration": best.get("duration") or media.get("video", {}).get("duration"),
        "quality": best.get("qualityType") or "",
        "poster": poster,
    }


def human_time(value: Any) -> str:
    try:
        stamp = int(value) / 1000
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    return datetime.fromtimestamp(stamp, BEIJING).strftime("%Y-%m-%d %H:%M")


def build_note(note: dict[str, Any], link: str) -> dict[str, Any]:
    user = note.get("user") or {}
    interact = note.get("interactInfo") or {}
    tags = [item.get("name") for item in (note.get("tagList") or [])
            if isinstance(item, dict) and item.get("name")]
    images = extract_images(note)
    video = extract_video(note)
    kind = "video" if note.get("type") == "video" else "image"
    return {
        "id": note.get("noteId") or note_id_of(link),
        "link": link,
        "kind": kind,
        "title": (note.get("title") or "").strip(),
        "desc": CONTROL.sub("", (note.get("desc") or "")),
        "tags": tags,
        "author": {
            "name": (user.get("nickname") or user.get("nickName") or "").strip(),
            "id": user.get("userId") or "",
            "avatar": user.get("avatar") or "",
        },
        "stats": {
            "liked": to_count(interact.get("likedCount")),
            "collected": to_count(interact.get("collectedCount")),
            "comment": to_count(interact.get("commentCount")),
            "share": to_count(interact.get("shareCount")),
        },
        "published": human_time(note.get("time")),
        "updated": human_time(note.get("lastUpdateTime")),
        "images": images,
        "video": video,
        # 视频作品的 imageList 只有封面帧；这个字段单独叫 cover，避免前端
        # 把它当成「N 张配图」展示给用户。
        "cover": images[0] if kind == "video" and images else None,
        "imageCount": 0 if kind == "video" else len(images),
    }


def fetch_note(link: str) -> dict[str, Any]:
    headers = dict(HEADERS)
    headers["referer"] = "https://www.xiaohongshu.com/"
    try:
        response = requests.get(link, headers=headers, timeout=20)
    except requests.Timeout as error:
        raise HTTPException(504, "小红书响应超时，请稍后重试") from error
    except requests.RequestException as error:
        raise HTTPException(502, "网络异常，暂时取不到这个小作品") from error
    if response.status_code >= 400:
        raise HTTPException(502, f"小红书返回 {response.status_code}，请稍后重试")
    note = _pick_note(parse_state(response.text))
    if not note:
        raise HTTPException(422, (
            "没读到作品数据。裸的作品链接（不带 xsec_token）拿不到内容："
            "请在小红书打开该作品，点「分享 → 复制链接」，把带 xsec_token 的整段链接粘进来"
        ))
    data = build_note(note, link)
    if not data["title"] and not data["desc"] and not data["images"] and not data["video"]:
        raise HTTPException(422, "该作品没有可提取的公开内容（可能已删除或仅作者可见）")
    return data


@router.post("/api/xhs/extract")
def api_extract(payload: ExtractRequest):
    """提取作品数据。只读公开信息，不下载、不落盘。"""
    link = normalize_link(payload.url)
    data = fetch_note(link)
    logger.info("xhs.extract id=%s kind=%s images=%s", data["id"], data["kind"], data["imageCount"])
    return {"status": "success", "note": data}


@router.get("/api/xhs/media")
def api_media(url: str = Query(min_length=8, max_length=2048)):
    """同源转发图片/视频，避免前端直接跨域拉小红书 CDN 被拦。

    只允许小红书自己的图床与视频域名，防止这个端点被当成任意 URL 的代理。
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host.endswith(
        ("xhscdn.com", "xiaohongshu.com", "rednote.com")
    ):
        raise HTTPException(400, "只允许转发小红书媒体地址")
    try:
        upstream = requests.get(
            url, headers={**HEADERS, "referer": "https://www.xiaohongshu.com/"},
            timeout=25, stream=True,
        )
    except requests.RequestException as error:
        raise HTTPException(502, "媒体下载失败") from error
    if upstream.status_code >= 400:
        upstream.close()
        raise HTTPException(502, "媒体下载失败")
    content_type = upstream.headers.get("content-type", "application/octet-stream")
    if not content_type.startswith(("image/", "video/")):
        upstream.close()
        raise HTTPException(415, "上游返回的不是图片或视频")

    def stream():
        try:
            for chunk in upstream.iter_content(64 * 1024):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    filename = quote(f"{note_id_of(url) or 'xhs'}-{parsed.path.rsplit('/', 1)[-1][:40]}")
    return StreamingResponse(
        stream(), media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=600",
            "Content-Disposition": f"inline; filename*=UTF-8''{filename}",
        },
    )
