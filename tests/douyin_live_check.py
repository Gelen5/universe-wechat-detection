"""抖音提取的联网自测：链接归一化、签名、真实作品、媒体代理、视频流。

不依赖数据库和登录态，只测 server/douyin_extract.py 这一层。文件名不以
``test_`` 开头，pytest 不会收集它 —— 它需要真实 Cookie 和外网，不适合进 CI。

运行：python tests/douyin_live_check.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

COOKIE_FILES = [
    Path(os.environ.get("DOUYIN_COOKIE_FILE", "")) if os.environ.get("DOUYIN_COOKIE_FILE") else None,
    Path.home() / ".agents/skills/douyin-video-parser/cookie_data/douyin_cookie.json",
]

REAL_VIDEO = "https://www.douyin.com/video/7699784646996823306"


def load_cookie() -> str:
    for candidate in COOKIE_FILES:
        if candidate and candidate.is_file():
            raw = candidate.read_text(encoding="utf-8").strip()
            if raw.startswith("{"):
                raw = json.loads(raw).get("cookie", "")
            if raw:
                print(f"[cookie] {candidate} -> {len(raw)} chars")
                return raw
    raise SystemExit("找不到可用的 DOUYIN_COOKIE，无法继续")


def check_normalize(module) -> None:
    cases = [
        (REAL_VIDEO, "7699784646996823306"),
        ("https://www.douyin.com/note/7699784646996823306", "7699784646996823306"),
        ("https://m.douyin.com/share/video/7699784646996823306", "7699784646996823306"),
        ("7699784646996823306", "7699784646996823306"),
        # 分享文案：夹说明文字、话题、短链
        ("8.43 复制打开抖音，看看【阿杭的作品】100w机会！ https://www.douyin.com/video/7699784646996823306?previous_page=app_code_link 长按复制",
         "7699784646996823306"),
    ]
    for raw, expected in cases:
        aweme_id, link = module.normalize_link(raw)
        assert aweme_id == expected, (raw, aweme_id)
        print(f"[normalize] ok -> {aweme_id}  ({raw[:42]}…)")

    for bad in ("https://www.xiaohongshu.com/explore/abc", "随便一段话"):
        try:
            module.normalize_link(bad)
        except Exception as error:
            print(f"[normalize] rejected {bad[:28]!r} -> {getattr(error, 'status_code', '?')}")
        else:
            raise AssertionError(f"应当拒绝：{bad}")


def check_missing_cookie(module) -> None:
    saved = os.environ.pop("DOUYIN_COOKIE", None)
    os.environ["DOUYIN_COOKIE_FILE"] = ""
    try:
        module._signed_request("7699784646996823306")
    except Exception as error:
        status = getattr(error, "status_code", None)
        print(f"[no-cookie] -> {status} {getattr(error, 'detail', error)}")
        assert status == 503, status
    else:
        raise AssertionError("没有 Cookie 时应当报 503")
    finally:
        if saved:
            os.environ["DOUYIN_COOKIE"] = saved


def check_real_extract(module) -> None:
    note = module.api_extract(module.ExtractRequest(url=REAL_VIDEO))["note"]
    print("[extract] kind=%s id=%s" % (note["kind"], note["id"]))
    print("[extract] title:", note["title"][:50])
    print("[extract] author:", note["author"]["name"], "| sec_uid:", bool(note["author"]["sec_uid"]))
    print("[extract] stats:", note["stats"])
    print("[extract] tags:", note["tags"][:4])
    print("[extract] published:", note["published"])
    if note["kind"] == "video":
        video = note["video"]
        assert video and video["url"].startswith("https://"), video
        print("[extract] video:", video["url"].split("?")[0][:70])
        print("[extract] video meta:", video["width"], video["height"], video["duration"], video["quality"])
        assert video["poster"], "视频应当有封面"
    else:
        assert note["images"], "图文作品应当有配图"
        print("[extract] images:", note["imageCount"], note["images"][0]["url"][:70])
    assert note["desc"], "应当有文案"


def check_media_endpoint(module) -> None:
    note = module.api_extract(module.ExtractRequest(url=REAL_VIDEO))["note"]
    url = note["video"]["poster"] if note["kind"] == "video" else note["images"][0]["url"]
    response = module.api_media(url=url)
    print("[media] type:", type(response).__name__, "| media_type:", getattr(response, "media_type", None))
    # 第二次应当命中磁盘缓存
    again = module.api_media(url=url)
    print("[media] second call:", type(again).__name__)
    try:
        module.api_media(url="https://example.com/a.png")
    except Exception as error:
        print("[media] refused foreign host ->", getattr(error, "status_code", "?"))
    else:
        raise AssertionError("非抖音域名应当被拒绝")


def check_video_stream(module) -> None:
    """视频走流式转发：真的把第一个 chunk 读出来，确认不是空壳。"""
    import asyncio

    response = module.api_video(id="7699784646996823306")
    media_type = getattr(response, "media_type", None)
    iterator = response.body_iterator

    async def take():
        try:
            return await iterator.__anext__()
        finally:
            close = getattr(iterator, "aclose", None)
            if close:
                await close()

    chunk = asyncio.run(take())
    print("[video] media_type:", media_type, "| first chunk bytes:", len(chunk or b""))
    assert media_type == "video/mp4", media_type
    assert chunk, "第一个 chunk 不该是空的"


def find_gallery_post(module) -> str | None:
    """在推荐流里找一条图文作品，用来验证 images 分支。"""
    params = dict(module.BASE_PARAMS)
    params.update({"count": "20", "refresh_index": "1", "video_type": "0"})
    try:
        raw_cookie = module._cookie()
    except Exception:
        return None
    jar = module._cookie_jar(raw_cookie)
    from server.douyin_signing import ABogus, encode_pairs, pick_uifid, websign

    bogus = ABogus(module.BROWSER_AGENT).get_value(encode_pairs(list(params.items())))
    pairs = list(params.items()) + [("a_bogus", bogus)]
    query, _signature, headers = websign(pairs, pick_uifid(jar) or "")
    request_headers = {
        "User-Agent": module.BROWSER_AGENT,
        "Referer": "https://www.douyin.com/",
        "Accept": "application/json, text/plain, */*",
        "Cookie": raw_cookie,
        **headers,
    }
    url = f"https://www.douyin.com/aweme/v1/web/tab/feed/?{query}"
    import requests

    response = requests.get(url, headers=request_headers, timeout=25)
    if response.status_code != 200:
        print("[gallery] feed status", response.status_code, "— 跳过")
        return None
    payload = response.json()
    for item in payload.get("aweme_list") or []:
        if item.get("images"):
            print("[gallery] found 图文:", item.get("aweme_id"), "images:", len(item["images"]))
            return item.get("aweme_id")
    print("[gallery] 这批推荐流里没有图文作品（正常，不视为失败）")
    return None


def check_gallery(module) -> None:
    aweme_id = find_gallery_post(module)
    if not aweme_id:
        return
    note = module.api_extract(
        module.ExtractRequest(url=f"https://www.douyin.com/note/{aweme_id}")
    )["note"]
    print("[gallery] kind=%s images=%s" % (note["kind"], note["imageCount"]))
    print("[gallery] title:", note["title"][:40])
    assert note["kind"] == "image", note["kind"]
    assert note["images"], "图文作品应当有配图"
    first = note["images"][0]
    assert first["url"].startswith("https://"), first
    print("[gallery] first image:", first["url"].split("?")[0][:70])
    response = module.api_media(url=first["url"])
    print("[gallery] media ->", type(response).__name__, getattr(response, "media_type", None))


def main() -> None:
    os.environ.setdefault("DOUYIN_COOKIE", load_cookie())
    os.environ.setdefault("DOUYIN_MEDIA_DIR", str(ROOT / "output/douyin-media-test"))

    from server import douyin_extract as module

    print("--- 链接归一化 ---")
    check_normalize(module)
    print("--- 缺凭据 ---")
    check_missing_cookie(module)
    print("--- 真实作品 ---")
    check_real_extract(module)
    print("--- 媒体代理 ---")
    check_media_endpoint(module)
    print("--- 图文作品 ---")
    check_gallery(module)
    print("--- 视频流式转发 ---")
    check_video_stream(module)
    print("\nALL OK")


if __name__ == "__main__":
    main()
