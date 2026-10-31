"""文章配图：贴一条公众号链接，拆解成图位，逐张生成 3:4 配图。

产品约束（来自需求确认）：
  * 所有图片固定 3:4（1086x1448），封面也不例外；
  * 先生成封面，用户确认满意后再生成剩余图位；
  * 图内所有文字必须取自文章原文，禁止编造数字与人名；
  * 正文图位只做信息海报（数据卡/时间线/结构拆解/对比/客户版图/金句），
    不做纯氛围插画——上一版就是因为画得好看但读者看不懂被否掉。
"""
from __future__ import annotations

import base64
import io
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from . import accounts, database, workbench

ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = ROOT / "output" / "article-visual"
JOB_LOCK = threading.RLock()

TARGET_W, TARGET_H = 1086, 1448
FORMS = ("cover", "data", "timeline", "layers", "compare", "clients", "quote")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# --------------------------------------------------------------------------- 抓取

def _meta(html: str, key: str) -> str:
    for pattern in (rf"var {key} = \"(.*?)\";", rf"var {key} = '(.*?)';"):
        match = re.search(pattern, html)
        if match:
            return match.group(1).strip()
    return ""


def extract_article(url: str) -> dict[str, Any]:
    """把公众号文章转成标题/作者/正文 Markdown/原图列表。"""
    if not re.match(r"^https?://mp\.weixin\.qq\.com/", url.strip()):
        raise ValueError("请粘贴 mp.weixin.qq.com 的公众号文章链接")
    response = requests.get(url.strip(), headers=HEADERS, timeout=25)
    response.raise_for_status()
    return parse_article_html(response.text, url.strip())


def parse_article_html(html: str, url: str = "") -> dict[str, Any]:
    """纯解析：给一段公众号 HTML，返回结构化文章。"""
    if 'id="js_content"' not in html:
        for reason in ("环境异常", "参数错误", "该内容已被发布者删除", "此内容因违规无法查看"):
            if reason in html:
                raise ValueError(f"文章打不开：{reason}")
        raise ValueError("没有解析到正文，可能被风控或文章已删除")

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    content = soup.find(id="js_content")
    if content is None:
        raise ValueError("没有解析到正文")

    title = ""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"].strip()
    if not title:
        h1 = soup.find(id="activity-name")
        title = h1.get_text(strip=True) if h1 else ""

    account_el = soup.find(id="js_name")
    account = account_el.get_text(strip=True) if account_el else _meta(html, "nickname")

    blocks: list[str] = []
    images: list[dict[str, str]] = []
    seen: set[str] = set()
    for el in content.find_all(
        ["h1", "h2", "h3", "h4", "p", "section", "li", "blockquote", "pre", "img"]
    ):
        if el.name == "img":
            src = el.get("data-src") or el.get("src") or ""
            if src:
                images.append({"src": src, "alt": el.get("alt", "")})
            continue
        # section 里往往还套着 p，跳过容器避免同一段抓两遍
        if el.name == "section" and el.find(["p", "section", "li", "blockquote", "pre"]):
            continue
        text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
        if not text or text in seen:
            continue
        seen.add(text)
        if el.name == "h1":
            blocks.append(f"# {text}")
        elif el.name == "h2":
            blocks.append(f"## {text}")
        elif el.name in ("h3", "h4"):
            blocks.append(f"### {text}")
        elif el.name == "blockquote":
            blocks.append(f"> {text}")
        elif el.name == "li":
            blocks.append(f"- {text}")
        else:
            blocks.append(text)

    publish = ""
    ct = _meta(html, "ct")
    if ct.isdigit():
        stamp = datetime.fromtimestamp(int(ct), tz=timezone.utc)
        publish = (stamp.astimezone().strftime("%Y-%m-%d %H:%M"))

    body = "\n\n".join(blocks)
    return {
        "url": url.strip(),
        "title": title,
        "account": account,
        "author": _meta(html, "author"),
        "publish_time": publish,
        "chars": len(body),
        "markdown": body,
        "images": images,
    }


# --------------------------------------------------------------------------- 拆解

PLAN_INSTRUCTION = """你是公众号视觉编辑。读这篇文章，产出一份配图方案。

硬性规则：
1. 只输出 JSON 对象，不要 markdown 代码块，不要任何解释。
2. 图里出现的每个数字、人名、公司名、结论都必须能在原文找到，禁止编造。
3. 结构固定为 1 个封面 + 2 到 4 个正文图位。正文图位按信息量取舍，不是每节都要配。
4. 正文 form 只能取以下之一：
   - data：一组关键数字（2-3 个）
   - timeline：有先后顺序的履历/阶段（3-5 个节点）
   - layers：结构分层、拆解、上下游关系
   - compare：两组对照（前后/两种做法/两个对象）
   - clients：客户、产品、应用场景这类并列清单
   - quote：全文最值得单独记住的一句话
5. 每个图位的文字要短：标题不超过 12 字，标签不超过 8 字，注脚不超过 20 字。
6. brief 只描述物件、场景、结构或抽象图形，禁止描写真实人物、名人姓名、合影、晚宴、会议等会出现可辨认人脸的场面。封面尤其要用「物件 + 场景」表达主题。

输出结构：
{
  "thesis": "一句话说清这篇文章在讲什么（20 字内）",
  "slots": [
    {
      "id": "cover",
      "form": "cover",
      "headline": "封面上最大的 4-8 个字（优先用数字或最刺激的钩子）",
      "kicker": "封面顶部一行小字，如榜单名/栏目名",
      "items": ["封面副标题一行", "封面底部一行人物或一句话"],
      "brief": "画面主体，一句话，不写排版也不写文字"
    },
    {
      "id": "body-01",
      "form": "data",
      "headline": "这张图的标题",
      "items": [{"value": "1270亿", "label": "周群飞身家", "note": "夫妇合计 1280 亿 · 第 33 位"}],
      "brief": "画面主体，一句话"
    },
    {
      "id": "body-02",
      "form": "timeline",
      "headline": "这张图的标题",
      "items": [{"year": "2007", "text": "初代 iPhone 玻璃"}],
      "brief": "画面主体，一句话"
    }
  ]
}

不同 form 的 items 写法：
- data: [{"value","label","note"}]，2-3 项
- timeline: [{"year","text"}]，3-5 项
- layers: [{"name","note"}]，2-4 层，从外到内或从上到下
- compare: [{"side":"左栏标题","points":["要点1","要点2"]},{"side":"右栏标题","points":["要点1","要点2"]}]
- clients: [{"name":"苹果"}] 或直接 ["苹果","特斯拉"]
- quote: items 留空数组

文章标题：__TITLE__
公众号：__ACCOUNT__

正文：
__BODY__
"""


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _extract_json(raw: str) -> dict[str, Any]:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型没有返回 JSON")
    return json.loads(raw[start : end + 1])


def _normalize_plan(raw: dict[str, Any], article: dict[str, Any]) -> dict[str, Any]:
    slots: list[dict[str, Any]] = []
    for index, slot in enumerate(raw.get("slots") or []):
        if not isinstance(slot, dict):
            continue
        form = str(slot.get("form") or "").strip().lower()
        if form not in FORMS:
            continue
        items = slot.get("items")
        if not isinstance(items, list):
            items = []
        slots.append(
            {
                "id": str(slot.get("id") or f"slot-{index + 1}")[:40],
                "form": form,
                "headline": _clip(str(slot.get("headline") or ""), 24),
                "kicker": _clip(str(slot.get("kicker") or ""), 24),
                "items": items[:6],
                "brief": _clip(str(slot.get("brief") or ""), 200),
            }
        )
    if not slots or slots[0]["form"] != "cover":
        slots.insert(
            0,
            {
                "id": "cover",
                "form": "cover",
                "headline": _clip(article["title"], 12),
                "kicker": article.get("account", ""),
                "items": [],
                "brief": "与文章主题相关的实物或场景",
            },
        )
    body_slots = [s for s in slots[1:] if s["form"] != "cover"]
    if not body_slots:
        body_slots = _fallback_slots(article)
    slots = [slots[0]] + body_slots[:4]
    for index, slot in enumerate(slots):
        slot["order"] = index
        slot["status"] = "pending"
    return {"thesis": _clip(str(raw.get("thesis") or article["title"]), 40), "slots": slots}


def _fallback_slots(article: dict[str, Any]) -> list[dict[str, Any]]:
    """模型掉链子时的兜底：只从正文里已经出现的数字和句子里取，不编造。"""
    body = article["markdown"]
    numbers = re.findall(r"\d[\d,.]*\s*(?:亿|万|%|个百分点)?", body)
    values: list[dict[str, str]] = []
    for value in numbers:
        if value.strip() and all(value.strip() != item["value"] for item in values):
            values.append({"value": value.strip(), "label": "", "note": ""})
        if len(values) == 3:
            break
    slots: list[dict[str, Any]] = []
    if values:
        slots.append(
            {
                "id": "body-01",
                "form": "data",
                "headline": "三个关键数字",
                "items": values,
                "brief": "深色财经数据卡",
            }
        )
    sentences = [s.strip() for s in re.split(r"[。！？\n]", body) if len(s.strip()) >= 12]
    if sentences:
        slots.append(
            {
                "id": "body-02",
                "form": "quote",
                "headline": _clip(sentences[0], 24),
                "items": [],
                "brief": "米白纸面的大字海报",
            }
        )
    return slots


def build_plan(article: dict[str, Any]) -> dict[str, Any]:
    prompt = (
        PLAN_INSTRUCTION.replace("__TITLE__", article["title"])
        .replace("__ACCOUNT__", article["account"])
        .replace("__BODY__", article["markdown"][:6000])
    )
    raw_text = ""
    try:
        raw_text = workbench._text(prompt)
        plan = _normalize_plan(_extract_json(raw_text), article)
    except Exception:
        plan = _normalize_plan({}, article)
    plan["source"] = "model" if raw_text else "fallback"
    return plan


# --------------------------------------------------------------------------- 提示词模板

STYLE_SUFFIX = "竖版构图，精确 3:4 比例。文字为中文，字号大而清晰，层级分明，装饰克制。"

# 真实人物和合影场面一律不进封面：模型会画出以假乱真的名人照片，
# 对新闻类文章这就是假图。命中这些词就换成物件景。
PEOPLE_SCENE_WORDS = (
    "马斯克", "库克", "周群飞", "合影", "晚宴", "圆桌", "并肩", "会面", "会谈",
    "峰会", "颁奖", "剪彩", "肖像", "半身像", "人物", "合影照",
)


def _safe_scene(brief: str) -> str:
    text = (brief or "").strip()
    if not text or any(word in text for word in PEOPLE_SCENE_WORDS):
        return "一件与文章主题相关的核心物件，立在深色台面上，边缘被冷光照亮"
    return text


def _join(values: list[Any], key: str) -> str:
    parts = []
    for item in values:
        if isinstance(item, dict):
            chunks = [str(item.get(k) or "").strip() for k in (key, "note")]
            text = "：".join([c for c in chunks if c])
        else:
            text = str(item).strip()
        if text:
            parts.append(text)
    return "；".join(parts)


def build_image_prompt(slot: dict[str, Any]) -> str:
    form = slot.get("form")
    headline = slot.get("headline") or ""
    items = slot.get("items") or []
    brief = slot.get("brief") or ""

    if form == "cover":
        kicker = slot.get("kicker") or ""
        sub = str(items[0]).strip() if items else ""
        bottom = str(items[1]).strip() if len(items) > 1 else ""
        scene = _safe_scene(brief)
        return (
            "竖版财经杂志封面设计，深黑蓝色背景，高级商业质感。"
            f"顶部一行小号金色中文「{kicker}」。"
            f"画面中部是超大的金色文字「{headline}」，无衬线粗体，占画面宽度的九成，是绝对视觉中心。"
            f"其下一行白色粗体中文「{sub}」。"
            f"画面主体：{scene}，从画面底部延伸上来托住文字，画面里只有物件与光影。"
            f"底部一行浅金色中文「{bottom}」。"
            "画面只出现以上这几行文字。黑金配色，对比强烈，像商业杂志封面。" + STYLE_SUFFIX
        )

    if form == "data":
        rows = []
        for item in items[:3]:
            if isinstance(item, dict):
                rows.append(
                    f"数字「{item.get('value','')}」，标注「{item.get('label','')}」"
                    + (f"，小字「{item.get('note','')}」" if item.get("note") else "")
                )
        body = "；".join(rows)
        return (
            "竖版财经数据海报，深墨蓝色背景，极细网格底纹，金色与白色为主色。"
            f"顶部一行白色中文标题「{headline}」。"
            f"下方纵向排列数据区块，用极细金线分隔：{body}。"
            "数字巨大，标签清楚，左对齐，装饰极简，留白充分。" + STYLE_SUFFIX
        )

    if form == "timeline":
        rows = []
        for item in items[:5]:
            if isinstance(item, dict):
                rows.append(f"「{item.get('year','')}」配「{item.get('text','')}」")
        return (
            "竖版极简时间线信息图，米白色纸张质感背景，深墨绿色文字与金色节点。"
            f"顶部一行深墨绿色中文标题「{headline}」。"
            "画面中部一条从上到下的竖直细线，线上等距排列节点；"
            f"每个节点左侧是年份、右侧是说明，从上到下依次为：{'；'.join(rows)}。"
            "衬线字体，印刷质感，留白充分。" + STYLE_SUFFIX
        )

    if form == "layers":
        rows = []
        for item in items[:4]:
            if isinstance(item, dict):
                rows.append(f"「{item.get('name','')}」标注「{item.get('note','')}」")
        return (
            "竖版产品结构示意图，深灰蓝色背景，精密工程制图风格。"
            f"顶部一行白色中文标题「{headline}」。"
            f"画面中部是层层拆开的结构图，层与层略微分开：{'；'.join(rows)}。"
            "每层用细线引出右侧标签，金色高亮最关键的一层。线条细而清晰。" + STYLE_SUFFIX
        )

    if form == "compare":
        columns = []
        for item in items[:2]:
            if isinstance(item, dict):
                points = "、".join(str(p) for p in (item.get("points") or [])[:3])
                columns.append(f"一侧标题「{item.get('side','')}」，下方要点「{points}」")
        return (
            "竖版左右对比信息图，深灰蓝背景，两栏用一条细金线分开。"
            f"顶部一行白色中文标题「{headline}」。"
            f"{'；'.join(columns)}。"
            "两栏结构对称，文字大而清晰，用颜色区分优劣。" + STYLE_SUFFIX
        )

    if form == "clients":
        names = []
        for item in items[:8]:
            names.append(str(item.get("name") if isinstance(item, dict) else item).strip())
        names = [n for n in names if n]
        return (
            "竖版商业信息图，深墨蓝色背景，金色点缀。"
            f"顶部一行白色中文标题「{headline}」。"
            f"画面中部是一块竖立的透明玻璃面板，面板两侧排列圆角标签：{'、'.join(names)}。"
            f"面板表面反射出与「{brief or headline}」相关的浅色轮廓。"
            "整体克制清晰，信息密度高。" + STYLE_SUFFIX
        )

    # quote
    return (
        "竖版大字海报，米白色纸张背景，深墨绿色文字。"
        f"画面居中排布中文大字「{headline}」，字大而醒目，分行自然。"
        "上方一条短金线，下方一行浅灰小字注明出处。极简，只有文字和纸面质感。" + STYLE_SUFFIX
    )


# --------------------------------------------------------------------------- 生图

def _image_bytes(result: dict[str, Any]) -> bytes:
    data = result.get("data") or []
    if not data:
        raise RuntimeError("图片接口没有返回图片")
    item = data[0] or {}
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    url = item.get("url")
    if url:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.content
    raise RuntimeError("图片接口返回格式无法识别")


def _fit_square(raw: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(raw)) as image:
        image = image.convert("RGB")
        width, height = image.size
        target_ratio = TARGET_W / TARGET_H
        if width / height > target_ratio:
            new_width = int(height * target_ratio)
            left = (width - new_width) // 2
            image = image.crop((left, 0, left + new_width, height))
        else:
            new_height = int(width / target_ratio)
            top = (height - new_height) // 2
            image = image.crop((0, top, width, top + new_height))
        image = image.resize((TARGET_W, TARGET_H), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def generate_slot_image(prompt: str) -> bytes:
    from .providers import ModelService, OpenAICompatibleProvider

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with workbench.provider_overrides():
                api_key = workbench._setting("WECHAT_IMAGE_API_KEY")
                if not api_key:
                    raise RuntimeError("服务端尚未配置图片 API Key")
                base_url = workbench._setting("WECHAT_IMAGE_API_BASE_URL") or workbench._setting(
                    "WECHAT_API_BASE_URL", "https://api.openai.com/v1"
                )
                model = workbench._setting("WECHAT_IMAGE_MODEL") or "gpt-image-2.5"
                provider = OpenAICompatibleProvider(
                    api_key=workbench._setting("WECHAT_TEXT_API_KEY") or api_key,
                    base_url=workbench._setting("WECHAT_TEXT_API_BASE_URL") or base_url,
                    text_model=workbench._setting("WECHAT_TEXT_MODEL", "gpt-4.1-mini"),
                    image_api_key=api_key,
                    image_base_url=base_url,
                    image_model=model,
                    verify_ssl=workbench._verify_ssl(),
                )
                # gpt-image-2.5 只接受 size=auto，比例靠 prompt 里写死，出图后再裁切
                result = ModelService(provider).generate_image(
                    prompt + "\n\n竖版构图，精确 3:4 比例。",
                    size="auto",
                    count=1,
                    timeout=180,
                )
            return _fit_square(_image_bytes(result))
        except Exception as exc:  # noqa: BLE001 - 逐次重试后把最后一次错误抛给前端
            last_error = exc
            if attempt == 0:
                time.sleep(2)
    raise RuntimeError(str(last_error) if last_error else "生成失败")


# --------------------------------------------------------------------------- 任务存储

_SCHEMA_READY = False


def _job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def _ensure_schema() -> None:
    """任务元数据进数据库；图片仍然落盘（对象存储是单独一件事）。"""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with database.session_scope() as session:
        session.execute(text(
            "CREATE TABLE IF NOT EXISTS article_visual_jobs ("
            "id VARCHAR(32) PRIMARY KEY, "
            "user_id VARCHAR(64) NOT NULL, "
            "payload TEXT NOT NULL, "
            "updated_at VARCHAR(40) NOT NULL)"
        ))
    _SCHEMA_READY = True


def _write_job(job: dict[str, Any]) -> None:
    _ensure_schema()
    now = datetime.now(timezone.utc).isoformat()
    payload = json.dumps(job, ensure_ascii=False)
    with database.session_scope() as session:
        session.execute(
            text(
                "INSERT INTO article_visual_jobs (id, user_id, payload, updated_at) "
                "VALUES (:id, :uid, :payload, :now) "
                "ON CONFLICT (id) DO UPDATE SET payload = :payload, updated_at = :now"
            ),
            {"id": job["id"], "uid": job["user_id"], "payload": payload, "now": now},
        )
    # 保留一份本地副本，方便排查和迁移
    directory = _job_dir(job["id"])
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / "job.json.tmp"
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(directory / "job.json")


def _read_job(job_id: str) -> dict[str, Any]:
    _ensure_schema()
    with database.session_scope() as session:
        row = session.execute(
            text("SELECT payload FROM article_visual_jobs WHERE id = :id"), {"id": job_id}
        ).fetchone()
    if row:
        return json.loads(row[0])
    legacy = _job_dir(job_id) / "job.json"
    if legacy.exists():
        return json.loads(legacy.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="任务不存在")


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    payload = dict(job)
    payload.pop("user_id", None)
    payload["slots"] = job["plan"]["slots"]
    payload["plan"] = {"thesis": job["plan"].get("thesis"), "source": job["plan"].get("source")}
    return payload


# --------------------------------------------------------------------------- 路由

router = APIRouter(prefix="/api/article-visual", tags=["article-visual"])


class PlanBody(BaseModel):
    url: str = Field(min_length=10, max_length=2000)


class GenerateBody(BaseModel):
    job_id: str = Field(min_length=4, max_length=32)
    slot_id: str = Field(min_length=1, max_length=40)
    headline: str | None = Field(default=None, max_length=24)


@router.post("/plan", status_code=201)
def create_plan(payload: PlanBody, request: Request):
    user = accounts.require_user(request)
    try:
        article = extract_article(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"抓取失败：{exc}") from exc

    plan = build_plan(article)
    job_id = uuid.uuid4().hex[:16]
    job = {
        "id": job_id,
        "user_id": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "article": {k: v for k, v in article.items() if k != "markdown"},
        "plan": plan,
        "images": {},
    }
    _job_dir(job_id).mkdir(parents=True, exist_ok=True)
    _job_dir(job_id).joinpath("article.md").write_text(article["markdown"], encoding="utf-8")
    _write_job(job)
    return _public_job(job)


@router.post("/generate")
def generate_one(payload: GenerateBody, request: Request):
    user = accounts.require_user(request)
    job_id = payload.job_id
    with JOB_LOCK:
        job = _read_job(job_id)
        if job["user_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="任务不存在")
        slot = next((s for s in job["plan"]["slots"] if s["id"] == payload.slot_id), None)
        if slot is None:
            raise HTTPException(status_code=404, detail="图位不存在")
        if payload.headline is not None:
            slot["headline"] = _clip(payload.headline, 24)
            _write_job(job)

    prompt = build_image_prompt(slot)
    try:
        raw = generate_slot_image(prompt)
    except Exception as exc:  # noqa: BLE001 - 前端需要可读的失败原因
        raise HTTPException(status_code=502, detail=f"生成失败：{exc}") from exc
    filename = f"{slot['id']}.png"
    path = _job_dir(job_id) / filename
    path.write_bytes(raw)

    with JOB_LOCK:
        job = _read_job(job_id)
        job["images"][slot["id"]] = {"file": filename, "prompt": prompt}
        for item in job["plan"]["slots"]:
            if item["id"] == slot["id"]:
                item["status"] = "done"
        _write_job(job)
    return {
        "slot_id": slot["id"],
        "url": f"/api/article-visual/{job_id}/images/{filename}",
        "prompt": prompt,
    }


@router.get("/{job_id}")
def get_job(job_id: str, request: Request):
    user = accounts.require_user(request)
    job = _read_job(job_id)
    if job["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _public_job(job)


@router.get("/{job_id}/images/{filename}")
def get_image(job_id: str, filename: str, request: Request):
    user = accounts.require_user(request)
    job = _read_job(job_id)
    if job["user_id"] != user["id"] or not re.fullmatch(r"[a-z0-9\-]{1,40}\.png", filename):
        raise HTTPException(status_code=404, detail="图片不存在")
    path = _job_dir(job_id) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})
