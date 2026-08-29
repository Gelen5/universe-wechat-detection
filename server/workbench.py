"""HTTP adapter for the installed weChat-autoCreate Skill.

Text generation and image generation deliberately use separate credentials.
The browser never receives either key. The installed Skill still owns
humanness scoring, Markdown conversion, themes and WeChat publishing.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

import requests


ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = Path(os.environ.get("WECHAT_AUTOCREATE_SKILL_DIR", r"C:\Users\16972\.codex\skills\weChat-autoCreate"))
OUTPUT_DIR = ROOT / "output" / "workbench"
SESSIONS: dict[str, dict[str, Any]] = {}
STEPS = ["选题", "框架", "写作", "反 AI", "配图", "排版", "预览", "发布"]
REQUEST_SETTINGS: ContextVar[dict[str, str]] = ContextVar("REQUEST_SETTINGS", default={})


class ProviderError(RuntimeError):
    pass


def _setting(name: str, default: str = "") -> str:
    overrides = REQUEST_SETTINGS.get()
    return (overrides.get(name) or os.getenv(name) or default).strip()


@contextmanager
def provider_overrides(
    text_api_key: str = "",
    image_api_key: str = "",
    text_base_url: str = "",
    image_base_url: str = "",
    text_model: str = "",
    image_model: str = "",
):
    values = {}
    if text_api_key.strip():
        values["WECHAT_TEXT_API_KEY"] = text_api_key.strip()
    if image_api_key.strip():
        values["WECHAT_IMAGE_API_KEY"] = image_api_key.strip()
    if text_base_url.strip():
        values["WECHAT_TEXT_API_BASE_URL"] = text_base_url.strip()
    if image_base_url.strip():
        values["WECHAT_IMAGE_API_BASE_URL"] = image_base_url.strip()
    if text_model.strip():
        values["WECHAT_TEXT_MODEL"] = text_model.strip()
    if image_model.strip():
        values["WECHAT_IMAGE_MODEL"] = image_model.strip()
    token = REQUEST_SETTINGS.set(values)
    try:
        yield
    finally:
        REQUEST_SETTINGS.reset(token)


def _verify_ssl() -> bool:
    return _setting("WECHAT_API_VERIFY_SSL", "true").lower() not in {"0", "false", "no", "off"}


def _api_url(channel: str, path: str) -> str:
    if channel == "text":
        base = _setting("WECHAT_TEXT_API_BASE_URL") or _setting("WECHAT_API_BASE_URL", "https://api.openai.com/v1")
    else:
        base = _setting("WECHAT_IMAGE_API_BASE_URL") or _setting("WECHAT_API_BASE_URL", "https://api.openai.com/v1")
    base = base.rstrip("/")
    return f"{base}/{path.lstrip('/')}"


def _headers(channel: str) -> dict[str, str]:
    env_name = "WECHAT_TEXT_API_KEY" if channel == "text" else "WECHAT_IMAGE_API_KEY"
    key = _setting(env_name)
    if not key:
        raise ProviderError(f"服务端尚未配置 {env_name}")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    actor = _setting("WECHAT_API_ACTOR_AUTH")
    if actor:
        headers["x-openai-actor-authorization"] = actor
    return headers


def _post(channel: str, path: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.post(
            _api_url(channel, path), headers=_headers(channel), json=payload,
            timeout=timeout, verify=_verify_ssl(),
        )
    except requests.RequestException as exc:
        raise ProviderError(f"{channel} API 连接失败：{exc}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderError(f"{channel} API 返回了非 JSON 响应（HTTP {response.status_code}）") from exc
    if not response.ok:
        error = data.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise ProviderError(f"{channel} API HTTP {response.status_code}：{message or '请求失败'}")
    return data


def _response_text(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    choices = data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = [item.get("text", "") for item in content if isinstance(item, dict)]
            text = "".join(part for part in parts if isinstance(part, str)).strip()
            if text:
                return text
    chunks: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    text = "\n".join(chunks).strip()
    if not text:
        raise ProviderError("文本 API 未返回可解析的 output_text")
    return text


def _text(prompt: str, *, reasoning: str = "medium") -> str:
    model = _setting("WECHAT_TEXT_MODEL", "gpt-4.1-mini")
    data = _post("text", "chat/completions", {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }, timeout=180)
    return _response_text(data)


def _json_text(prompt: str) -> dict[str, Any]:
    raw = _text(prompt)
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ProviderError("文本 API 没有返回要求的 JSON 对象")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ProviderError("文本 API 返回的 JSON 无法解析") from exc


def provider_status() -> dict[str, Any]:
    return {
        "text": {"configured": bool(_setting("WECHAT_TEXT_API_KEY")), "model": _setting("WECHAT_TEXT_MODEL", "未配置")},
        "image": {"configured": bool(_setting("WECHAT_IMAGE_API_KEY")), "model": _setting("WECHAT_IMAGE_MODEL", "未配置")},
        "text_base_url_configured": bool(_setting("WECHAT_TEXT_API_BASE_URL") or _setting("WECHAT_API_BASE_URL")),
        "image_base_url_configured": bool(_setting("WECHAT_IMAGE_API_BASE_URL") or _setting("WECHAT_API_BASE_URL")),
    }


def _suggestions(topic: str, persona: str) -> list[dict[str, Any]]:
    seed = topic.strip() or "适合公众号读者的高价值内容"
    data = _json_text(f"""你是微信公众号资深选题编辑。围绕用户方向「{seed}」，为「{persona}」写作人格生成10个差异明显、可以真正展开的中文选题。
要求：避免编造热点数据；标题要具体、自然、有读者收益；覆盖观点、教程、故事、对比、清单、案例、趋势、复盘等类型。
只返回合法JSON，不要Markdown：{{"topics":[{{"title":"...","type":"观点","reason":"推荐理由","heat":8,"competition":"中"}}]}}。topics必须正好10项。""")
    items = data.get("topics") or []
    if len(items) < 10:
        raise ProviderError("文本 API 返回的选题不足10个")
    result = []
    for index, item in enumerate(items[:10], 1):
        result.append({
            "id": index,
            "title": str(item.get("title") or "").strip(),
            "type": str(item.get("type") or "观点").strip(),
            "reason": str(item.get("reason") or "具备可展开空间").strip(),
            "heat": max(1, min(10, int(item.get("heat") or 7))),
            "competition": str(item.get("competition") or "中").strip(),
            "source": "text-api",
        })
    if any(not item["title"] for item in result):
        raise ProviderError("文本 API 返回了空选题")
    return result


def _framework(title: str, persona: str) -> dict[str, Any]:
    data = _json_text(f"""你是微信公众号主编。为文章《{title}》选择最合适的一个框架，只能从 SCQA、AIDA、PES、时间线、对比、问题树、飞轮 中选择。
写作人格：{persona}。给出5个具体到内容层的小标题，不要写空泛模板。
只返回合法JSON：{{"name":"SCQA","reason":"...","outline":["...","...","...","...","..."]}}。""")
    outline = [str(item).strip() for item in (data.get("outline") or []) if str(item).strip()]
    if len(outline) < 4:
        raise ProviderError("文本 API 返回的文章框架不完整")
    return {"name": str(data.get("name") or "SCQA"), "reason": str(data.get("reason") or "根据主题自动选择"), "outline": outline[:6], "source": "text-api"}


def _draft(title: str, frame: dict[str, Any], persona: str) -> str:
    outline = "\n".join(f"- {item}" for item in frame.get("outline", []))
    article = _text(f"""你是「{persona}」型微信公众号作者。请按 weChat-autoCreate Skill 的写作规范，完成一篇可以继续编辑的中文公众号长文。
标题：{title}
框架：{frame.get('name')}
结构：
{outline}

硬性要求：
1. 1800至2600字，Markdown格式，第一行是一级标题。
2. 开头从具体生活场景或冲突进入，不使用“在当今时代”等空话。
3. 每段尽量不超过180字，句长有变化；避免“首先、其次、最后”“值得注意的是”“总而言之”。
4. 不编造研究、人物经历、统计数字或引用。没有来源的事实明确写成观察或判断。
5. 至少给出3个可执行建议，结尾留一个具体互动问题。
6. 不要解释写作过程，只输出文章正文。""", reasoning="high")
    if len(article) < 800:
        raise ProviderError("文本 API 返回的文章过短")
    return article


def _review(article: str) -> tuple[str, dict[str, Any]]:
    reviewed = _text(f"""你是微信公众号终审编辑。对下面文章执行反AI与事实边界修订：保留作者核心观点和Markdown结构；删除套话、机械排比和虚构事实；提升细节、口语自然度和段落节奏；不得新增无法验证的数据、案例或引用。只输出修订后的完整Markdown文章，不写说明。

文章：
{article}""", reasoning="high")
    return reviewed, {"source": "text-api", "model": _setting("WECHAT_TEXT_MODEL"), "action": "反AI与事实边界修订"}


def _score(text: str) -> dict[str, Any]:
    script = SKILL_DIR / "scripts" / "humanness_score.py"
    if not script.exists():
        return {"status": "unavailable", "message": "未找到 Skill 评分脚本"}
    result = subprocess.run(
        [sys.executable, str(script), "--text", text, "--json", "--no-calibration"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    if result.returncode != 0:
        return {"status": "unavailable", "message": result.stderr[-500:] or "评分失败"}
    try:
        data = json.loads(result.stdout)
        return {"status": "success", "score": data.get("final_score", 50), "raw_score": data.get("raw_score", 50), "layers": data.get("layers", {})}
    except json.JSONDecodeError:
        return {"status": "unavailable", "message": "评分结果不是合法 JSON"}


def _compress_image(raw: bytes, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("RGB")
            quality = 88
            while quality >= 58:
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
                if buffer.tell() <= 950_000 or quality == 58:
                    output.write_bytes(buffer.getvalue())
                    return output.stat().st_size
                quality -= 6
    except ImportError as exc:
        raise ProviderError("服务器缺少 Pillow，无法压缩微信配图") from exc
    raise ProviderError("生成图片压缩失败")


def _generate_image(prompt: str, output: Path) -> dict[str, Any]:
    model = _setting("WECHAT_IMAGE_MODEL", "gpt-image-2")
    raw: bytes | None = None
    last_shape = "empty"
    for attempt in range(2):
        request_prompt = prompt if attempt == 0 else f"{prompt}。画面自然、友善、适合大众阅读。"
        data = _post("image", "images/generations", {
            "model": model, "prompt": request_prompt, "n": 1,
            "size": "1024x1024", "output_format": "png",
        }, timeout=360)
        items = data.get("data") or []
        item = items[0] if isinstance(items, list) and items else {}
        last_shape = f"root={','.join(sorted(data.keys()))}; item={','.join(sorted(item.keys())) if isinstance(item, dict) else type(item).__name__}"
        if isinstance(item, dict) and item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"])
            break
        if isinstance(item, dict) and item.get("url"):
            downloader = requests.Session()
            downloader.trust_env = False
            response = downloader.get(item["url"], timeout=90, verify=_verify_ssl())
            response.raise_for_status()
            raw = response.content
            break
    if not raw:
        raise ProviderError(f"图片 API 连续两次未返回图片（{last_shape}）")
    size = _compress_image(raw, output)
    return {"file": output.name, "bytes": size, "model": model, "prompt": prompt}


def _images(session: dict[str, Any]) -> list[dict[str, Any]]:
    title = session["topic"]
    outline = session.get("framework", {}).get("outline", [])
    prompts = [
        ("cover", f"微信公众号文章封面，主题《{title}》，成熟克制的中文编辑插画风，无文字，无水印，主体位于画面右侧，左侧留出标题空间，温暖自然光，画面高级简洁"),
        ("body", f"微信公众号正文配图，表达《{title}》中的核心冲突：{outline[1] if len(outline)>1 else title}，纪实感编辑插画，无文字，无水印，构图清晰，情绪真实克制"),
    ]
    output_dir = OUTPUT_DIR / session["id"] / "images"
    result = []
    for index, (kind, prompt) in enumerate(prompts, 1):
        image = _generate_image(prompt, output_dir / f"{kind}-{index}.jpg")
        image.update({"kind": kind, "url": f"/api/workbench/assets/{session['id']}/{image['file']}"})
        result.append(image)
    return result


def _session_view(session: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in session.items() if k != "files"}


def create(topic: str, mode: str = "interactive", persona: str = "深度观察者", theme: str = "default") -> dict[str, Any]:
    sid = uuid.uuid4().hex
    session: dict[str, Any] = {
        "id": sid, "topic": topic.strip(), "mode": mode, "persona": persona, "theme": theme,
        "current_step": 1, "status": "calling_text_api", "suggestions": [], "framework": None,
        "article": "", "review": None, "score": None, "images": [], "preview_url": None,
        "publish": None, "provider": provider_status(), "created_at": datetime.now().isoformat(timespec="seconds"), "files": {},
    }
    SESSIONS[sid] = session
    session["suggestions"] = _suggestions(topic, persona)
    session["status"] = "awaiting_topic"
    if mode == "auto":
        _advance(session, 7)
        session["current_step"] = 8
        session["status"] = "complete"
    return _session_view(session)


def _advance(session: dict[str, Any], target: int, selection: int | None = None) -> dict[str, Any]:
    target = max(1, min(8, target))
    if target >= 2 and session["framework"] is None:
        chosen = session["suggestions"][selection - 1] if selection and 1 <= selection <= len(session["suggestions"]) else session["suggestions"][0]
        session["topic"] = chosen["title"]
        session["selected_topic"] = chosen
        session["status"] = "calling_text_api"
        session["framework"] = _framework(session["topic"], session["persona"])
    if target >= 3 and not session["article"]:
        session["status"] = "calling_text_api"
        session["article"] = _draft(session["topic"], session["framework"], session["persona"])
    if target >= 4 and session["article"] and not session["review"]:
        session["status"] = "calling_text_api"
        session["article"], session["review"] = _review(session["article"])
        session["score"] = _score(session["article"])
    if target >= 5 and not session["images"]:
        session["status"] = "calling_image_api"
        session["images"] = _images(session)
    if target >= 6:
        session["status"] = "rendering"
    if target >= 7:
        preview(session["id"])
    session["current_step"] = target
    session["status"] = "complete" if target == 8 else ("ready_for_review" if session["mode"] == "interactive" and target in (1, 2, 5) else "running")
    return _session_view(session)


def step(session_id: str, target: int, selection: int | None = None, article: str | None = None) -> dict[str, Any]:
    session = SESSIONS.get(session_id)
    if not session:
        raise KeyError("创作会话不存在或已过期")
    if article is not None and article.strip() and article != session.get("article"):
        session["article"] = article
        session["score"] = None
        session["review"] = None
    return _advance(session, target, selection)


def preview(session_id: str, article: str | None = None) -> dict[str, Any]:
    session = SESSIONS.get(session_id)
    if not session:
        raise KeyError("创作会话不存在或已过期")
    if article is not None and article.strip():
        session["article"] = article
    session["score"] = _score(session["article"])
    image_markdown = ""
    for image in session.get("images", []):
        label = "文章封面" if image["kind"] == "cover" else "正文配图"
        image_markdown += f"\n\n![{label}]({image['url']})\n"
    output_dir = OUTPUT_DIR / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "article.md"
    output.write_text(f"---\ntitle: '{session['topic'].replace(chr(39), '')}'\ntheme: {session['theme']}\n---\n{image_markdown}\n{session['article']}", encoding="utf-8")
    html = output_dir / "preview.html"
    result = subprocess.run(
        [sys.executable, "-m", "toolkit.cli", "preview", str(output), "--output", str(html), "--theme", session["theme"]],
        cwd=str(SKILL_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-700:] or "Skill 预览失败")
    session["preview_url"] = f"/api/workbench/preview/{session_id}"
    session["current_step"] = 7
    return _session_view(session)


def preview_file(session_id: str) -> Path:
    return OUTPUT_DIR / session_id / "preview.html"


def asset_file(session_id: str, filename: str) -> Path:
    return OUTPUT_DIR / session_id / "images" / Path(filename).name


def publish(session_id: str, draft: bool = True) -> dict[str, Any]:
    session = SESSIONS.get(session_id)
    if not session:
        raise KeyError("创作会话不存在或已过期")
    appid = _setting("WECHAT_APPID") or _setting("WECHAT_APP_ID")
    secret = _setting("WECHAT_SECRET") or _setting("WECHAT_APP_SECRET")
    if not appid or not secret:
        session["publish"] = {"status": "blocked", "message": "未配置公众号 AppID / AppSecret；已保留本地预览，请配置后再写入草稿箱。"}
        return _session_view(session)
    output = OUTPUT_DIR / session_id / "article.md"
    if not output.exists():
        preview(session_id)
    args = [sys.executable, "-m", "toolkit.cli", "publish", str(output), "--theme", session["theme"]]
    if not draft:
        args.append("--no-draft")
    result = subprocess.run(args, cwd=str(SKILL_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    session["publish"] = {"status": "success" if result.returncode == 0 else "failed", "message": (result.stdout or result.stderr)[-1000:]}
    return _session_view(session)
