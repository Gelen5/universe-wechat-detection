"""HTTP adapter for the installed wechat-publisher-ultimate Skill.

Text generation and image generation deliberately use separate credentials.
The browser never receives either key. The installed Skill still owns
humanness scoring, Markdown conversion, themes and WeChat publishing.
"排版"等确定性步骤直接调用 Skill 自带的 converter / theme 引擎（经 Skill 的 venv Python 运行），
不修改 Skill 源码，也不在本项目里另写一套伪排版。
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

import requests
from . import accounts


ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = Path(os.environ.get("WECHAT_PUBLISHER_SKILL_DIR") or (
    r"C:\Users\16972\Documents\skill\tmp\weChat-autoCreate" if os.name == "nt"
    else "/opt/universe-skills/weChat-autoCreate"
))
ANTI_AI_SKILL_DIR = Path(os.environ.get("UNIVERSE_ANTI_AI_SKILL_DIR") or (
    r"C:\Users\16972\.workbuddy\skills\universe-delete-ai-skill" if os.name == "nt"
    else "/opt/universe-skills/universe-delete-ai-skill"
))
OUTPUT_DIR = ROOT / "output" / "workbench"
SESSIONS: dict[str, dict[str, Any]] = {}
CANCEL_REQUESTS: set[str] = set()
STEPS = ["选题", "框架", "写作", "反 AI", "配图", "排版", "预览", "发布"]
REQUEST_SETTINGS: ContextVar[dict[str, str]] = ContextVar("REQUEST_SETTINGS", default={})


def _skill_python() -> str:
    """返回 wechat-publisher-ultimate 自带的 venv Python（含 markdown/bs4/yaml 等依赖）。

    找不到时退回当前解释器，由调用方处理依赖缺失。
    """
    candidates = [
        SKILL_DIR / ".venv" / "Scripts" / "python.exe",
        SKILL_DIR / ".venv" / "bin" / "python",
        SKILL_DIR / "venv" / "Scripts" / "python.exe",
        SKILL_DIR / "venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def skill_status() -> dict[str, Any]:
    required = [
        SKILL_DIR / "SKILL.md", SKILL_DIR / "toolkit" / "converter.py",
        SKILL_DIR / "toolkit" / "theme.py", SKILL_DIR / "toolkit" / "cli.py",
        SKILL_DIR / "toolkit" / "recommendation_quality.py",
    ]
    return {
        "ready": all(path.exists() for path in required),
        "path": str(SKILL_DIR),
        "python": _skill_python(),
        "missing": [str(path.relative_to(SKILL_DIR)) for path in required if not path.exists()],
    }


def _require_skill() -> None:
    status = skill_status()
    if not status["ready"]:
        raise RuntimeError(f"wechat-publisher-ultimate Skill 未完整安装：{', '.join(status['missing'])}")


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
    if not any((text_api_key, image_api_key, text_base_url, image_base_url, text_model, image_model)):
        from . import accounts
        stored = accounts.provider_settings(include_secrets=True)
        text_api_key = stored.get("text_api_key", "")
        image_api_key = stored.get("image_api_key", "")
        text_base_url = stored.get("text_base_url", "")
        image_base_url = stored.get("image_base_url", "")
        text_model = stored.get("text_model", "")
        image_model = stored.get("image_model", "")
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


def _resolve_image_response(data: dict[str, Any], timeout: int = 360) -> dict[str, Any]:
    """Resolve providers that return an asynchronous image task first."""
    status_url = data.get("statusUrl") or data.get("status_url")
    if not status_url or data.get("data"):
        return data

    deadline = time.time() + timeout
    last_payload = data
    session = requests.Session()
    session.trust_env = False
    while time.time() < deadline:
        time.sleep(3)
        try:
            response = session.get(
                str(status_url), headers=_headers("image"), timeout=35,
                verify=_verify_ssl(),
            )
        except requests.RequestException as exc:
            raise ProviderError(f"image API 任务查询失败：{exc}") from exc
        try:
            last_payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"image API 任务返回了非 JSON 响应（HTTP {response.status_code}）") from exc
        if not response.ok:
            error = last_payload.get("error") if isinstance(last_payload, dict) else None
            if isinstance(error, dict):
                error = error.get("message") or error.get("code")
            raise ProviderError(str(error or last_payload.get("message") or f"image API HTTP {response.status_code}"))
        status = str(last_payload.get("status") or "").lower()
        if last_payload.get("data") or status in {"completed", "succeeded", "success"}:
            return last_payload
        if status in {"failed", "cancelled", "canceled", "error"}:
            error = last_payload.get("error")
            if isinstance(error, dict):
                error = error.get("message") or error.get("code")
            raise ProviderError(str(error or last_payload.get("message") or f"图片任务失败：{status}"))
    raise ProviderError(f"图片任务等待超时，最后状态：{last_payload.get('status') or '未知'}")


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
    article = _text(f"""你是「{persona}」型微信公众号作者。请按 wechat-publisher-ultimate Skill 的写作规范，完成一篇可以继续编辑的中文公众号长文。
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


def _review(article: str, session: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """第4步反AI：按 universe-delete-ai-skill 的 standard 档位方法论改写，
    并用该 Skill 的 audit_revision.py 做确定性二次审计（信号量 + 保护片段核对）。"""
    reviewed = _text(f"""你是按 universe-delete-ai-skill 方法论工作的中文改稿编辑。对下面文章执行一次 standard 档位改写（信息骨架可靠，只做局部去模板化）。

改写规则（全部来自该 Skill，必须遵守）：
1. 先建保护片段账：数字、日期、时间跨度、人物/组织/产品名、原话、链接、代码、指标和限定词默认不改；若事实主体、责任归属、动作、因果方向或判断强度发生变化，立即回滚该处修改。
2. 修改顺序：事实边界 → 主语/指代 → 句子主干 → 段落承接 → 空泛重复 → 句式变化。只改能指出位置和原因的问题，不改变事实顺序、段落主线和判断强度。
3. 优先处理整篇层面风险：段落是否都用"观点—解释—总结"同一骨架、连续三项排比、每段金句收尾、抽象主语替代具体行动、商业黑话或工程师腔。确认存在后先改结构和主语，不做机械同义词替换。
4. 压缩、扁化、去情绪不是去AI味，是在刮人味：不删情绪词、不合并并列的生活细节、不删前后呼应的细节、不删真实的对话互动。叙述者可以保留态度和判断。
5. 可读性硬门槛：至少90%句子有明确主语或承接对象并有完整动作或判断；每个独立陈述用自然的句末标点收束；"他/她/这/那/其实/后来"指代不清时写回具体对象；复杂句先说谁做了什么。
6. 禁止：新增原文不存在的研究、数据、经历、心理或对白；错别字、漏标点、强行口语、固定闲笔、假自我矛盾。
7. 只输出修订后的完整 Markdown 文章，不写任何说明。

文章：
{article}""", reasoning="high")
    audit = _anti_ai_audit(article, reviewed, session)
    info = {
        "source": "universe-delete-ai-skill",
        "model": _setting("WECHAT_TEXT_MODEL"),
        "action": "standard 档位去AI改写（universe-delete-ai-skill 方法论）",
        "audit": audit,
    }
    return reviewed, info


def _anti_ai_audit(original: str, revision: str, session: dict[str, Any]) -> dict[str, Any]:
    """调用 universe-delete-ai-skill 的 audit_revision.py：改稿前后信号对比 + 保护片段核对。"""
    script = ANTI_AI_SKILL_DIR / "scripts" / "audit_revision.py"
    if not script.exists():
        return {"status": "unavailable", "message": "未找到 universe-delete-ai-skill 审计脚本"}
    workdir = OUTPUT_DIR / session["id"] / "anti_ai"
    workdir.mkdir(parents=True, exist_ok=True)
    orig_path = workdir / "original.txt"
    rev_path = workdir / "revision.txt"
    orig_path.write_text(original, encoding="utf-8")
    rev_path.write_text(revision, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(orig_path), str(rev_path), "--mode", "standard", "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ANTI_AI_SKILL_DIR / "scripts"), timeout=60,
    )
    if result.returncode != 0:
        return {"status": "unavailable", "message": result.stderr[-500:] or "审计失败"}
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "unavailable", "message": "审计结果不是合法 JSON"}
    revised = data.get("revision") or {}
    readability = revised.get("readability") or {}
    return {
        "status": "success",
        "mode": data.get("mode"),
        "original_signal_total": (data.get("original") or {}).get("signal_total"),
        "revision_signal_total": revised.get("signal_total"),
        "missing_protected_spans": data.get("missing_protected_spans") or {},
        "complete_sentence_ratio": readability.get("complete_sentence_ratio"),
        "sentence_length_cv": (readability.get("sentence_length") or {}).get("cv"),
        "warnings": readability.get("warnings", []),
    }


def _score(text: str) -> dict[str, Any]:
    script = SKILL_DIR / "scripts" / "humanness_score.py"
    if not script.exists():
        return {"status": "unavailable", "message": "未找到 Skill 评分脚本"}
    result = subprocess.run(
        [_skill_python(), str(script), "--text", text, "--json", "--no-calibration"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(SKILL_DIR), timeout=60,
    )
    if result.returncode != 0:
        return {"status": "unavailable", "message": result.stderr[-500:] or "评分失败"}
    try:
        data = json.loads(result.stdout)
        return {"status": "success", "score": data.get("final_score", 50), "raw_score": data.get("raw_score", 50), "layers": data.get("layers", {})}
    except json.JSONDecodeError:
        return {"status": "unavailable", "message": "评分结果不是合法 JSON"}


def _build_article_markdown(session: dict[str, Any]) -> str:
    image_markdown = ""
    for image in session.get("images", []):
        label = "文章封面" if image["kind"] == "cover" else "正文配图"
        image_markdown += f"\n\n![{label}]({image['url']})\n"
    return (
        f"---\ntitle: '{session['topic'].replace(chr(39), '')}'\ntheme: {session['theme']}\n"
        f"---\n{image_markdown}\n{session['article']}"
    )


def _typeset(session: dict[str, Any]) -> str:
    """第6步排版：调用 Skill CLI，执行质量门禁、转换、主题与富文本复制预览。"""
    _require_skill()
    md = _build_article_markdown(session)
    output_dir = OUTPUT_DIR / session["id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "article.md"
    markdown_path.write_text(md, encoding="utf-8")
    generated_preview = output_dir / "article_preview.html"
    generated_preview.unlink(missing_ok=True)
    result = subprocess.run(
        [_skill_python(), "-m", "toolkit.cli", "preview", str(markdown_path), "--theme", session["theme"]],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(SKILL_DIR), timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2000:] or "Skill 排版质量门禁未通过")
    if not generated_preview.exists():
        raise RuntimeError("Skill 排版完成但未生成预览 HTML")
    document = generated_preview.read_text(encoding="utf-8")
    match = re.search(r'<main id="article-content">(.*?)</main>', document, flags=re.S)
    if not match:
        raise RuntimeError("Skill 预览缺少可复制的 article-content 区域")
    session["typeset_html"] = match.group(1).strip()
    session["preview_document"] = document
    session["typeset_source"] = "wechat-publisher-ultimate"
    return session["typeset_html"]


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
        data = _resolve_image_response(data)
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
    output_dir.mkdir(parents=True, exist_ok=True)
    result = []
    for index, (kind, prompt) in enumerate(prompts, 1):
        if session["id"] in CANCEL_REQUESTS:
            raise ProviderError("已取消本次生成")
        image = _generate_image(prompt, output_dir / f"{kind}-{index}.jpg")
        image.update({"kind": kind, "url": f"/api/workbench/assets/{session['id']}/{image['file']}"})
        result.append(image)
    return result


def _session_view(session: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in session.items() if k not in {"user_id", "files", "typeset_html", "preview_document"}}


def _save_session(session: dict[str, Any]) -> None:
    user_id = session.get("user_id")
    if not user_id:
        raise RuntimeError("创作会话缺少用户归属")
    SESSIONS[session["id"]] = session
    accounts.save_workbench_session(user_id, session)


def _get_session(session_id: str, user_id: str) -> dict[str, Any]:
    session = SESSIONS.get(session_id)
    if session and session.get("user_id") == user_id:
        return session
    session = accounts.load_workbench_session(session_id, user_id)
    if not session:
        raise KeyError("创作会话不存在、已过期或不属于当前用户")
    SESSIONS[session_id] = session
    return session


def create(topic: str, mode: str = "interactive", persona: str = "深度观察者", theme: str = "default",
           *, user_id: str, session_id: str | None = None) -> dict[str, Any]:
    sid = session_id or uuid.uuid4().hex
    session: dict[str, Any] = {
        "id": sid, "user_id": user_id, "topic": topic.strip(), "mode": mode, "persona": persona, "theme": theme,
        "current_step": 1, "status": "calling_text_api", "suggestions": [], "framework": None,
        "article": "", "review": None, "score": None, "images": [], "typeset_html": "", "preview_document": "", "typeset_source": None, "preview_url": None,
        "publish": None, "provider": provider_status(), "created_at": datetime.now().isoformat(timespec="seconds"), "files": {},
        "conversation": ([{"role": "user", "content": topic.strip(), "at": datetime.now().isoformat(timespec="seconds")}] if topic.strip() else []),
        "versions": [], "last_change": "等待你确认写作方向",
    }
    _save_session(session)
    session["suggestions"] = _suggestions(topic, persona)
    session["status"] = "awaiting_topic"
    session["conversation"].append({"role": "assistant", "content": "我先为你拆出了三种可展开的写法方向。你可以直接采用其中一个，也可以继续告诉我：想更犀利、更多故事，还是换一个受众。", "at": datetime.now().isoformat(timespec="seconds")})
    if mode == "auto":
        _advance(session, 7)
        session["current_step"] = 8
        session["status"] = "complete"
    _save_session(session)
    return _session_view(session)


def _advance(session: dict[str, Any], target: int, selection: int | None = None) -> dict[str, Any]:
    if session["id"] in CANCEL_REQUESTS:
        raise ProviderError("已取消本次生成")
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
        session["article"], session["review"] = _review(session["article"], session)
        session["score"] = _score(session["article"])
    if target >= 5 and not session["images"]:
        session["status"] = "calling_image_api"
        session["images"] = _images(session)
    if target >= 6 and not session.get("typeset_html"):
        session["status"] = "rendering"
        _typeset(session)
    if target >= 7:
        preview(session["id"])
    session["current_step"] = target
    session["status"] = "complete" if target == 8 else ("ready_for_review" if session["mode"] == "interactive" and target in (1, 2, 5) else "running")
    return _session_view(session)


def step(session_id: str, target: int, selection: int | None = None, article: str | None = None,
         *, user_id: str) -> dict[str, Any]:
    session = _get_session(session_id, user_id)
    CANCEL_REQUESTS.discard(session_id)
    if article is not None and article.strip() and article != session.get("article"):
        session["article"] = article
        session["score"] = None
        session["review"] = None
        session["typeset_html"] = ""
        session["preview_document"] = ""
        session["typeset_source"] = None
    result = _advance(session, target, selection)
    _save_session(session)
    return result


def cancel(session_id: str, *, user_id: str) -> dict[str, Any]:
    """Request cancellation of the current synchronous step."""
    _get_session(session_id, user_id)
    CANCEL_REQUESTS.add(session_id)
    return {"status": "cancelling", "message": "已收到取消请求，当前图片请求结束后会停止后续生成"}


def chat(session_id: str, message: str, action: str = "rewrite_article", selection_text: str = "", *, user_id: str) -> dict[str, Any]:
    """Apply a conversational revision while preserving the current article session."""
    session = _get_session(session_id, user_id)
    message = message.strip()
    if not message:
        raise ValueError("请先告诉我你希望怎么调整")
    conversation = session.setdefault("conversation", [])
    conversation.append({"role": "user", "content": message, "at": datetime.now().isoformat(timespec="seconds")})
    versions = session.setdefault("versions", [])
    if session.get("article"):
        versions.append({"label": f"V{len(versions) + 1}", "summary": session.get("last_change") or "调整前版本", "article": session["article"]})
        versions[:] = versions[-8:]

    if action == "regenerate_topics":
        # A new direction starts a fresh branch.  Keeping the previous outline or
        # article here made the next "采用" action silently reuse stale content.
        session.update({
            "selected_topic": None,
            "framework": None,
            "article": "",
            "review": None,
            "score": None,
            "images": [],
            "typeset_html": "",
            "preview_url": "",
            "published": None,
        })
        session["topic"] = message
        session["suggestions"] = _suggestions(message, session["persona"])
        session["current_step"] = 1
        session["status"] = "awaiting_topic"
        reply = "好的，我已经把上一版收进版本记录，先按你刚才的新要求重新拆了三种方向。"
    elif not session.get("framework"):
        session["topic"] = message
        session["suggestions"] = _suggestions(message, session["persona"])
        session["current_step"] = 1
        session["status"] = "awaiting_topic"
        reply = "我重新整理了三个更适合展开的方向。选一个采用，或继续告诉我你真正想写的角度。"
    elif action == "regenerate_framework":
        session["framework"] = _framework(session["topic"], session["persona"])
        session["current_step"] = 2
        session["status"] = "ready_for_review"
        reply = "框架已换一版。你可以先看骨架，也可以直接让我把它写成完整文章。"
    else:
        original = selection_text.strip() or session.get("article") or ""
        if not original:
            session["article"] = _draft(session["topic"], session["framework"], session["persona"])
        else:
            scope = "只改写下面选中的段落，其余文章保持不变" if selection_text.strip() else "改写整篇文章"
            prompt = f"""你是资深微信公众号编辑。用户正在与写作助手共同修改文章。
文章标题：{session['topic']}
写作人格：{session['persona']}
用户要求：{message}
处理范围：{scope}
原文：
{original}

请直接输出修改后的中文正文，不要解释、不用 Markdown 标题、不加任何前言。保留真实边界，不编造事实或数据。"""
            rewritten = _text(prompt)
            if selection_text.strip():
                session["article"] = (session.get("article") or "").replace(selection_text, rewritten, 1)
            else:
                session["article"] = rewritten
        session["current_step"] = max(3, int(session.get("current_step") or 3))
        session["status"] = "ready_for_review"
        session["review"] = None
        session["score"] = None
        session["typeset_html"] = ""
        session["preview_document"] = ""
        session["typeset_source"] = None
        reply = "已经按你的要求更新了当前草稿。你可以继续对某一段提出要求，或让我再生成一版。"
    session["last_change"] = message[:80]
    conversation.append({"role": "assistant", "content": reply, "at": datetime.now().isoformat(timespec="seconds")})
    _save_session(session)
    view = _session_view(session)
    view["chat_reply"] = reply
    return view


def preview(session_id: str, article: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
    if user_id is None:
        cached = SESSIONS.get(session_id)
        if not cached:
            raise KeyError("创作会话不存在或已过期")
        user_id = cached["user_id"]
    session = _get_session(session_id, user_id)
    if article is not None and article.strip():
        session["article"] = article
        session["typeset_html"] = ""
        session["preview_document"] = ""
        session["typeset_source"] = None
    session["score"] = _score(session["article"])
    # 第6步与预览都复用 wechat-publisher-ultimate CLI：质量门禁、主题排版和
    # 微信富文本复制逻辑保持为同一条 Skill 链路。
    if not session.get("typeset_html"):
        _typeset(session)
    output_dir = OUTPUT_DIR / session_id
    output_dir.mkdir(parents=True, exist_ok=True)
    html = output_dir / "preview.html"
    html.write_text(session["preview_document"], encoding="utf-8")
    session["preview_url"] = f"/api/workbench/preview/{session_id}"
    session["html_download_url"] = f"/api/workbench/html/{session_id}"
    session["current_step"] = 7
    _save_session(session)
    return _session_view(session)


def preview_file(session_id: str) -> Path:
    return OUTPUT_DIR / session_id / "preview.html"


def asset_file(session_id: str, filename: str) -> Path:
    return OUTPUT_DIR / session_id / "images" / Path(filename).name


def publish(session_id: str, draft: bool = True, *, user_id: str) -> dict[str, Any]:
    session = _get_session(session_id, user_id)
    appid = _setting("WECHAT_APPID") or _setting("WECHAT_APP_ID")
    secret = _setting("WECHAT_SECRET") or _setting("WECHAT_APP_SECRET")
    if not appid or not secret:
        session["publish"] = {"status": "blocked", "message": "未配置公众号 AppID / AppSecret；已保留本地预览，请配置后再写入草稿箱。"}
        _save_session(session)
        return _session_view(session)
    output = OUTPUT_DIR / session_id / "article.md"
    if not output.exists():
        preview(session_id)
    args = [_skill_python(), "-m", "toolkit.cli", "publish", str(output), "--theme", session["theme"]]
    if not draft:
        args.append("--no-draft")
    result = subprocess.run(args, cwd=str(SKILL_DIR), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    session["publish"] = {"status": "success" if result.returncode == 0 else "failed", "message": (result.stdout or result.stderr)[-1000:]}
    _save_session(session)
    return _session_view(session)
