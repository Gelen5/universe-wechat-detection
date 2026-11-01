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
import contextvars
import io
import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime, timedelta, timezone
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
_PLAN_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="article-plan")
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

MOBILE_HEADERS = {
    **HEADERS,
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
    ),
    "Referer": "https://mp.weixin.qq.com/",
}

# 同一链接 10 分钟内复用解析结果：用户失败重试、或部署重启后重试时
# 不必再打一次微信，减少被「环境异常」拦的概率。
_ARTICLE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


# --------------------------------------------------------------------------- 抓取

def _meta(html: str, key: str) -> str:
    for pattern in (rf"var {key} = \"(.*?)\";", rf"var {key} = '(.*?)';"):
        match = re.search(pattern, html)
        if match:
            return match.group(1).strip()
    return ""


def extract_article(url: str) -> dict[str, Any]:
    """把公众号文章转成标题/作者/正文 Markdown/原图列表。"""
    # 微信分享出来常带一段标题文字，直接取其中的链接，别让用户自己裁。
    match = re.search(r"https?://mp\.weixin\.qq\.com/[^\s\u3000]+", url or "")
    if not match:
        raise ValueError("请粘贴 mp.weixin.qq.com 的公众号文章链接")
    link = match.group(0).rstrip("，。；、）)】\"'")

    cached = _ARTICLE_CACHE.get(link)
    if cached and time.time() - cached[0] < 600:
        return cached[1]

    last_error: Exception | None = None
    for headers in (HEADERS, MOBILE_HEADERS):
        try:
            response = requests.get(link, headers=headers, timeout=(5, 12))
            response.raise_for_status()
            article = parse_article_html(response.text, link)
            _ARTICLE_CACHE[link] = (time.time(), article)
            return article
        except ValueError as exc:
            last_error = exc
            # 链接本身参数错误，换 UA 也没用，直接报给用户
            if "参数错误" in str(exc):
                break
        except requests.RequestException as exc:
            last_error = exc
    if isinstance(last_error, ValueError):
        raise last_error
    raise last_error or ValueError("抓取失败")


def parse_article_html(html: str, url: str = "") -> dict[str, Any]:
    """纯解析：给一段公众号 HTML，返回结构化文章。"""
    if 'id="js_content"' not in html:
        for reason in ("环境异常", "参数错误", "该内容已被发布者删除", "此内容因违规无法查看"):
            if reason in html:
                hint = ""
                if reason == "参数错误":
                    hint = "（链接可能被截断，请在微信里重新复制完整链接）"
                elif reason == "环境异常":
                    hint = "（微信拦了这次访问，过几分钟再试）"
                raise ValueError(f"文章打不开：{reason}{hint}")
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

PLAN_INSTRUCTION = """你是公众号视觉编辑。你的任务不是"配几张图"，而是用 4-6 张图把这篇文章讲清楚。

先想清楚三件事：
A. 这篇文章最反常识、最有信息量的结论是什么？
B. 支撑这个结论的有哪 3-5 个要点？每个要点要有：结论、一句解释、原文里的事实（数字/对比/案例）。
C. 读者只看这组图，能不能复述出文章的核心？

硬性规则：
1. 只输出 JSON 对象，不要 markdown 代码块，不要任何解释。
2. 图里出现的每个数字、产品名、结论都必须来自原文，禁止编造。
3. 图里禁止出现公众号名称、作者名、媒体名、来源信息；只讲内容本身。
4. 结构：1 个封面 + 3 到 5 个正文图位。每个正文图位只讲一个要点，不要与封面重复。
5. headline 必须是"爆点"：一句让人愿意停下来看的结论，不超过 14 字。封面优先用原文最硬的数字（如 13.8 万 Star）或最反常识的结论。不要写"三个关键数字""核心要点"这类空话。
6. detail 是一句解释，不超过 30 字，必须说清这张图在讲什么。
7. facts 是 2-3 条原文事实（数字、对比、专有名词），每条不超过 16 字，用来支撑 headline。
8. brief 描述画面主体：具体物件、场景、结构；不写排版、不写文字；禁止真实人物、名人、合影。
9. 封面 kicker 用主题标签（如「AI 工具」「开源项目」），禁止用公众号名称。
10. 正文 form 只能取：compare（问题 vs 解法、前后差异）、layers（机制/结构/流程）、data（一组关键数字）、timeline（有先后顺序）、clients（并列清单）、quote（全篇最值得记住的一句）。
11. 每个图位必须给 visual 字段，取值只能是 photo（实景摄影）、light（浅色杂志）、paper（纸张笔记）、iso（3D 等距）、dark（深色海报）。一套图至少用 3 种，dark 最多 2 张，禁止全部深色。
12. 每张图必须有具体视觉主体（实物、场景、界面、产品），禁止"纯色底板 + 大字"这种只有文字的海报。

输出结构：
{
  "thesis": "一句话说清这篇文章的核心结论（25 字内）",
  "slots": [
    {
      "id": "cover",
      "form": "cover",
      "headline": "全文最大爆点，可含数字，不超过 14 字",
      "visual": "photo",
      "kicker": "主题标签，如 AI 工具",
      "items": ["副标题：一句话说清它解决什么", "底部一行：最值得记住的结论"],
      "brief": "画面主体，具体物件或场景"
    },
    {
      "id": "body-01",
      "form": "compare",
      "visual": "light",
      "headline": "爆点结论",
      "detail": "一句话解释",
      "facts": ["事实1", "事实2"],
      "items": [
        {"side": "没有规范", "points": ["配色靠猜", "每页间距不一样"]},
        {"side": "先定规范", "points": ["按业务检索", "后续页面继承"]}
      ],
      "brief": "画面主体"
    },
    {
      "id": "body-02",
      "form": "layers",
      "visual": "iso",
      "headline": "爆点结论",
      "detail": "一句话解释",
      "facts": ["事实1", "事实2"],
      "items": [{"name": "检索", "note": "按业务找风格"}, {"name": "落地", "note": "存成规范"}],
      "brief": "画面主体"
    }
  ]
}

不同 form 的 items 写法：
- compare: [{"side":"左栏标题","points":["要点1","要点2"]},{"side":"右栏标题","points":["要点1","要点2"]}]
- layers: [{"name","note"}]，2-4 层
- data: [{"value","label","note"}]，2-3 项
- timeline: [{"year","text"}]，3-5 项
- clients: [{"name":"苹果"}] 或 ["苹果","特斯拉"]
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
                "detail": _clip(str(slot.get("detail") or ""), 60),
                "facts": [
                    _clip(str(fact), 24)
                    for fact in (slot.get("facts") or [])
                    if str(fact).strip()
                ][:3],
                "kicker": _clip(str(slot.get("kicker") or ""), 24),
                "visual": str(slot.get("visual") or "").strip().lower(),
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
                "detail": "",
                "facts": [],
                "kicker": "",
                "items": [],
                "brief": "与文章主题相关的实物或场景",
            },
        )
    body_slots = [s for s in slots[1:] if s["form"] != "cover"]
    if not body_slots:
        body_slots = _fallback_slots(article)
    slots = [slots[0]] + body_slots[:5]
    account = (article.get("account") or "").strip()
    for slot in slots:
        # 别人的公众号名字绝不进图：kicker 里出现就直接清空，
        # 条目里带账号名的整条丢掉。
        if account:
            if slot.get("kicker") == account or account in (slot.get("kicker") or ""):
                slot["kicker"] = ""
            slot["items"] = [
                item for item in slot["items"]
                if account not in json.dumps(item, ensure_ascii=False)
            ]
    rotation = ("photo", "light", "paper", "iso", "dark")
    for index, slot in enumerate(slots):
        # 模型没给或给了不认识的风格，就按顺序轮换，保证一套图不会全是深色。
        if slot.get("visual") not in VISUAL_STYLES:
            slot["visual"] = rotation[index % len(rotation)]
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


def _text_with_deadline(prompt: str, *, model: str, reasoning: str, timeout: float) -> str:
    """在线程里调模型并卡死上限。

    线上实测 haiku 这条链路会卡到 134 秒才报 transport 错，把用户晾在
    「拆解中」；单靠 provider 自己的 300 秒超时救不了体验。
    """
    # ContextVar 不会自动带进新线程，必须把 provider_overrides 的上下文复制过去，
    # 否则线程里读到空 base_url，会去连 api.openai.com 直接失败。
    context = contextvars.copy_context()
    future = _PLAN_POOL.submit(
        context.run, workbench._text, prompt, model=model, reasoning=reasoning
    )
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        future.cancel()
        raise TimeoutError(f"{model} 超过 {int(timeout)} 秒没有返回") from exc


def plan_model() -> str:
    """配图策划用的模型。

    2026-11-01 实测：claude-sonnet-5-5 走同一个中转站 11.4 秒返回合法 JSON
    （5 个图位），比 gpt-6.1-sol 的 55 秒快一个量级；此前注释里「Anthropic 系
    transport 失败卡 133 秒」的结论已经不成立。留一个环境变量，万一中转站抽风
    可以立刻切回 Sol。
    """
    return (workbench._setting("WECHAT_ARTICLE_VISUAL_MODEL")
            or "claude-sonnet-5-5")


def build_plan(article: dict[str, Any]) -> dict[str, Any]:
    prompt = (
        PLAN_INSTRUCTION.replace("__TITLE__", article["title"])
        .replace("__ACCOUNT__", article["account"])
        .replace("__BODY__", article["markdown"][:4000])
    )
    # 90 秒硬上限（上游为抗抖动调高过）：超时就退回规则拆解，绝不让用户无限等。
    # Sonnet-5.5 实测 11 秒，余量足够。
    raw_text = ""
    try:
        stored = accounts.provider_settings(include_secrets=True)
        with workbench.provider_overrides(
            text_api_key=stored.get("text_api_key", ""),
            text_base_url=stored.get("text_base_url", ""),
            text_model=stored.get("text_model", ""),
            image_api_key=stored.get("image_api_key", ""),
            image_base_url=stored.get("image_base_url", ""),
            image_model=stored.get("image_model", ""),
        ):
            raw_text = _text_with_deadline(
                prompt, model=plan_model(), reasoning="low", timeout=90
            )
    except Exception:
        raw_text = ""
    try:
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


def _fact_chips(facts: list[str]) -> str:
    chips = "、".join(f"「{fact}」" for fact in facts[:3] if fact)
    return f"画面底部横向排列事实标签：{chips}。" if chips else ""


def _clean_label(text: str, limit: int = 22) -> str:
    """模型爱写「副标题：」「底部一行：」，这些是字段名，不能印到图上。"""
    value = re.sub(r"^(副标题|主标题|底部一行|底部|小字|标题)[：:]\s*", "", (text or "").strip())
    return value[:limit].rstrip()


def _base_image_prompt(slot: dict[str, Any], cover_style: str = "compare") -> str:
    form = slot.get("form")
    headline = slot.get("headline") or ""
    detail = slot.get("detail") or ""
    facts = slot.get("facts") or []
    items = slot.get("items") or []
    brief = slot.get("brief") or ""
    sub_line = f"标题下方一行白色中文小字「{detail}」。" if detail else ""
    chips = _fact_chips(facts)

    if form == "cover":
        kicker = slot.get("kicker") or ""
        sub = _clean_label(str(items[0])) if items else ""
        bottom = _clean_label(str(items[1])) if len(items) > 1 else ""
        scene = _safe_scene(brief)
        badge = (facts[0] if facts else "") or kicker
        if cover_style == "number":
            return (
                "竖版数字冲击海报，纯黑背景，极简大字报风格。"
                "画面中央是巨大的白色中文粗体「" + headline + "」，占画面宽度九成、高度约四成，"
                "是整个画面的绝对主角。"
                f"其下一行亮黄色中文粗体「{sub}」，字高约百分之八。"
                + (f"再下一行白色小字「{bottom}」。 " if bottom else " ")
                + f"底部一行浅灰小字「{badge}」。 "
                "背景只有很淡的设计网格、色板和字体线稿，不抢主体。"
                "文字锐利，高对比。" + STYLE_SUFFIX
            )
        if cover_style == "object":
            return (
                "竖版实物海报，深色桌面上的静物特写，强侧光，印刷品质感。"
                f"画面主体：{scene}。"
                f"画面上方压一行粗体白色中文「{headline}」，占画面宽度八成，字重很粗。"
                f"其后一行浅灰中文小字「{sub}」。"
                + (f"右下角一枚亮黄色标签，写黑色中文「{badge}」。 " if badge else " ")
                + "构图干净，主体清晰，只有一个视觉焦点。" + STYLE_SUFFIX
            )
        # compare：默认，问题状态 vs 解决状态的强对比
        return (
            "竖版对比海报，画面上下（或左右）分成两半，中间一条粗黑分隔线。"
            f"一半是问题状态：{scene}，配色刺眼、排版混乱、元素歪斜；"
            "另一半是解决后的状态：同样的主体，配色克制、网格整齐、留白干净。"
            f"画面上方压一行超大红色中文「{headline}」，粗黑体，是画面最强的视觉元素。"
            f"其下一行白色中文「{sub}」。"
            + (f"角落一枚亮黄色徽章，写黑色中文「{badge}」。 " if badge else " ")
            + "背景深灰，对比强烈，文字锐利。" + STYLE_SUFFIX
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
            f"{sub_line}"
            f"下方纵向排列数据区块，用极细金线分隔：{body}。"
            f"{chips}"
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
            f"{sub_line}"
            "画面中部一条从上到下的竖直细线，线上等距排列节点；"
            f"每个节点左侧是年份、右侧是说明，从上到下依次为：{'；'.join(rows)}。"
            f"{chips}衬线字体，印刷质感，留白充分。" + STYLE_SUFFIX
        )

    if form == "layers":
        rows = []
        for item in items[:4]:
            if isinstance(item, dict):
                rows.append(f"「{item.get('name','')}」标注「{item.get('note','')}」")
        return (
            "竖版产品结构示意图，深灰蓝色背景，精密工程制图风格。"
            f"顶部一行白色中文标题「{headline}」。"
            f"{sub_line}"
            f"画面中部是层层拆开的结构图，层与层略微分开：{'；'.join(rows)}。"
            "每层用细线引出右侧标签，金色高亮最关键的一层。线条细而清晰。"
            f"{chips}" + STYLE_SUFFIX
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
            f"{sub_line}"
            f"{'；'.join(columns)}。"
            "两栏结构对称，文字大而清晰，用颜色区分优劣。"
            f"{chips}" + STYLE_SUFFIX
        )

    if form == "clients":
        names = []
        for item in items[:8]:
            names.append(str(item.get("name") if isinstance(item, dict) else item).strip())
        names = [n for n in names if n]
        return (
            "竖版商业信息图，深墨蓝色背景，金色点缀。"
            f"顶部一行白色中文标题「{headline}」。"
            f"{sub_line}"
            f"画面中部是一块竖立的透明玻璃面板，面板两侧排列圆角标签：{'、'.join(names)}。"
            f"面板表面反射出与「{brief or headline}」相关的浅色轮廓。"
            "整体克制清晰，信息密度高。"
            f"{chips}" + STYLE_SUFFIX
        )

    # quote
    return (
        "竖版大字海报，米白色纸张背景，深墨绿色文字。"
        f"画面居中排布中文大字「{headline}」，字大而醒目，分行自然。"
        f"{sub_line}"
        "上方一条短金线，下方一行浅灰小字注明出处。极简，只有文字和纸面质感。"
        f"{chips}" + STYLE_SUFFIX
    )


# --------------------------------------------------------------------------- 生图

# 一套图不能全是黑底大字：每个图位由策划模型指定视觉风格，缺省按实景摄影轮换。
VISUAL_STYLES = {
    "photo": {
        "desc": "真实摄影质感，浅色桌面或真实场景，自然光，浅景深",
        "bg": "浅灰木质桌面与柔和自然光的实景背景",
        "ink": "深墨色",
        "accent": "暖黄色",
    },
    "light": {
        "desc": "浅色杂志编辑设计，米白纸张，细线分隔，留白充分",
        "bg": "米白色纸张背景",
        "ink": "深墨绿色",
        "accent": "金色",
    },
    "paper": {
        "desc": "手工纸与铅笔线稿的说明图，轻微做旧，像工作笔记",
        "bg": "暖米色手工纸背景",
        "ink": "深棕色",
        "accent": "砖红色",
    },
    "iso": {
        "desc": "3D 等距插画，浅灰蓝背景，柔和投影，干净几何形体",
        "bg": "浅灰蓝色背景",
        "ink": "深蓝色",
        "accent": "亮黄色",
    },
    "dark": {
        "desc": "深色电影感海报，强对比，用一个光源塑形",
        "bg": "深黑蓝色背景",
        "ink": "白色",
        "accent": "金色",
    },
}

_BG_REPLACEMENTS = (
    "纯黑背景",
    "深墨蓝色背景",
    "深灰蓝色背景",
    "深黑蓝色背景",
    "米白色纸张质感背景",
    "米白色纸张背景",
    "深色桌面上的静物特写",
)


def build_image_prompt(slot: dict[str, Any], cover_style: str = "compare") -> str:
    """在基础版式上套视觉风格，并强制每张图必须有具体主体。"""
    prompt = _base_image_prompt(slot, cover_style)
    style = VISUAL_STYLES.get(str(slot.get("visual") or ""), VISUAL_STYLES["photo"])
    for background in _BG_REPLACEMENTS:
        prompt = prompt.replace(background, style["bg"])
    prompt = prompt.replace("白色中文", f"{style['ink']}中文").replace("白色小字", f"{style['ink']}小字")
    prompt = prompt.replace("金色与白色为主色", f"{style['accent']}与{style['ink']}为主色")
    subject = _safe_scene(slot.get("brief") or "") or f"与「{slot.get('headline') or ''}」相关的实物"
    lock = (
        f"整体视觉：{style['desc']}。"
        f"画面必须出现具体视觉主体（{subject}），主体占画面至少一半；"
        "禁止纯色底板只放文字，禁止只有渐变和光效。"
    )
    return f"{lock}{prompt}"

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
    try:
        _refund_stale_reservations()
    except Exception:  # noqa: BLE001 - 对账失败不该挡住正常请求
        pass


def _refund_stale_reservations(max_age_minutes: int = 15) -> int:
    """容器重启会打断请求，预扣的积分必须退回去。

    中间件是「先扣后跑」，进程被部署/重启杀掉时没有机会走退款分支，
    usage_records 会留下 reserved 行。这里把超过 15 分钟还没结算的退回。
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).isoformat()
    with database.session_scope() as session:
        rows = session.execute(
            text(
                "SELECT request_id FROM usage_records "
                "WHERE path LIKE :prefix AND status = 'reserved' AND created_at < :cutoff"
            ),
            {"prefix": "/api/article-visual/%", "cutoff": cutoff},
        ).fetchall()
    refunded = 0
    for (request_id,) in rows:
        accounts.refund_usage(request_id, 499, 0)
        refunded += 1
    return refunded


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
    cover_style: str | None = Field(default=None, pattern="^(compare|number|object)$")


@router.post("/plan", status_code=201)
def create_plan(payload: PlanBody, request: Request):
    started = time.perf_counter()
    user = accounts.require_user(request)
    try:
        article = extract_article(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"抓取失败：{exc}") from exc

    plan = build_plan(article)
    if plan.get("source") != "model":
        # 宁可明确失败并退款，也不要把「三个关键数字」这种兜底方案塞给用户。
        raise HTTPException(
            status_code=504,
            detail="拆解模型这次没返回（超时或上游异常），积分已自动退回，请重试一次",
        )
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
    result = _public_job(job)
    result["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    return result


@router.post("/generate")
def generate_one(payload: GenerateBody, request: Request):
    started = time.perf_counter()
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

    prompt = build_image_prompt(slot, cover_style=payload.cover_style or "compare")
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
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
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
