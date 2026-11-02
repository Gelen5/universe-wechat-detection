"""Public, crawlable pages that explain the workbench's real capabilities.

The application UI is intentionally a client-side workspace.  Search engines
need a small set of stable HTML pages as well, rather than a list of keywords
in the application shell.
"""
from html import escape
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response


router = APIRouter()
SITE = "https://yuzoudiyigongzuotai.cn"
STATIC = Path(__file__).resolve().parents[1] / "static"
VERIFY_FILE = "baidu_verify_codeva-g1x7XWVb4z.html"

PAGES = {
    "ai-writing": {
        "title": "AI 写作工作台｜公众号、小红书内容创作工具｜宇宙第一工作台",
        "description": "宇宙第一工作台为内容创作者提供 AI 写作、公众号文章创作、标题优化、排版与发布前复核能力。把选题、写作、修改和交付放在同一个工作台完成。",
        "h1": "面向内容创作者的 AI 写作工作台",
        "lead": "不是把一段提示词丢进聊天框，而是把选题、草稿、改稿、排版和复核连成一条可继续推进的创作流程。",
        "sections": [
            ("公众号 AI 写作", "从选题开始形成公众号文章草稿，支持标题、表达优化、HTML 编辑排版和带格式复制。内容由创作者确认后再进入下一步。"),
            ("小红书内容创作", "根据产品、受众和表达重点生成可继续修改的内容包，帮助创作者把灵感落为图文或视频的基础稿。"),
            ("发布前复核", "在发布前检查标题承诺、正文价值和表达风险，给出具体的修改方向，而不是只给一个泛泛的分数。"),
        ],
    },
    "wechat-official-account": {
        "title": "公众号创作工作台｜AI 写文章、排版与发布前复核｜宇宙第一工作台",
        "description": "公众号创作工作台集成 AI 写作、文章排版、标题优化、配图规划与发布前复核，帮助公众号运营者更稳定地完成内容生产。",
        "h1": "公众号创作，从一篇草稿走到可交付文章",
        "lead": "为公众号运营准备的工作区：保留你的判断，让 AI 负责推进重复的创作环节。",
        "sections": [
            ("写作与改稿", "围绕选题、目标读者和已有素材生成草稿，并可继续调整表达、结构和标题，不把一次生成当作最终成品。"),
            ("微信排版", "在编辑器里完成文章排版，复制时提供适合粘贴到公众号后台的富文本内容，减少格式来回损耗。"),
            ("配图与复核", "根据文章规划配图位置和视觉方向，再在发布前检查内容是否兑现标题、是否有明确价值和需要补足的地方。"),
        ],
    },
    "sticker-account": {
        "title": "微信贴图号工具｜贴图文案、卡片策划与 AI 配图｜宇宙第一工作台",
        "description": "宇宙第一工作台提供贴图号内容策划、卡片文案、视觉方向和 AI 配图生成能力，帮助创作者更快完成一组可发布的微信贴图内容。",
        "h1": "把贴图号的一组内容，做成完整的表达",
        "lead": "先确定主题和卡片表达，再生成对应的画面，而不是只批量出图。",
        "sections": [
            ("贴图号策划", "围绕一个主题拆出卡片顺序、每张卡的作用、文案和视觉重点，让整组贴图有统一的情绪与节奏。"),
            ("AI 卡片配图", "按已确认的卡片信息生成图片，并保留每张图的用途和来源记录，方便继续调整与交付。"),
            ("内容质量检查", "在生成过程中检查视觉主体、比例、文字安全区等基础条件，减少看起来像一组却用不起来的图片。"),
        ],
    },
    "ai-skills": {
        "title": "AI Skill 工作台｜内容创作 Skill 与创作者工具｜宇宙第一工作台",
        "description": "宇宙第一工作台把公众号创作、贴图号、小红书、账号诊断、爆文复核等 AI Skill 集成到一个面向中文内容创作者的工作台。",
        "h1": "一个围绕内容创作的 AI Skill 工作台",
        "lead": "不同工作需要不同工具。工作台把可继续使用的创作能力组织在一起，而不是要求你记住一堆分散的提示词。",
        "sections": [
            ("内容创作 Skill", "公众号文章、小红书内容、贴图号策划、早安祝福等任务各有独立的工作流和输出格式。"),
            ("运营与诊断 Skill", "账号诊断、爆文检测、表达改写和内容拆解，帮助创作者在创作之外也能做出运营判断。"),
            ("统一工作区", "在一个账号和工作区中保存创作过程、任务进度和可交付内容，避免工具切换时丢掉上下文。"),
        ],
    },
}


def _page(slug: str) -> str:
    page = PAGES[slug]
    canonical = f"{SITE}/{slug}"
    sections = "".join(
        f"<section><h2>{escape(heading)}</h2><p>{escape(body)}</p></section>"
        for heading, body in page["sections"]
    )
    schema = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": page["title"],
        "description": page["description"],
        "url": canonical,
        "inLanguage": "zh-CN",
        "isPartOf": {"@type": "WebSite", "name": "宇宙第一工作台", "url": SITE},
    }
    import json
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(page["title"])}</title><meta name="description" content="{escape(page["description"], quote=True)}">
<link rel="canonical" href="{canonical}"><meta property="og:type" content="website"><meta property="og:title" content="{escape(page["title"], quote=True)}"><meta property="og:description" content="{escape(page["description"], quote=True)}"><meta property="og:url" content="{canonical}">
<script type="application/ld+json">{json.dumps(schema, ensure_ascii=False).replace("</", "<\\/")}</script>
<style>body{{margin:0;color:#18231d;background:#f7f6f1;font:16px/1.8 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}main{{max-width:860px;margin:auto;padding:48px 24px 72px}}nav{{font-size:14px}}a{{color:#17633f;text-decoration:none}}a:hover{{text-decoration:underline}}.brand{{font-weight:700;color:#18231d}}h1{{font-size:clamp(32px,6vw,52px);line-height:1.18;letter-spacing:-.04em;margin:72px 0 20px}}.lead{{font-size:20px;max-width:700px;color:#42544a}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:48px 0}}section{{background:#fff;border:1px solid #e7e7df;border-radius:16px;padding:22px}}h2{{font-size:19px;line-height:1.35;margin:0 0 10px}}p{{margin:0;color:#526058}}.cta{{display:inline-block;margin-top:30px;padding:12px 19px;background:#17633f;border-radius:999px;color:white;font-weight:650}}footer{{margin-top:56px;color:#758078;font-size:13px}}@media(max-width:680px){{main{{padding-top:24px}}h1{{margin-top:52px}}.grid{{grid-template-columns:1fr}}}}</style></head>
<body><main><nav><a class="brand" href="/">宇宙第一工作台</a>　/　<a href="/ai-writing">AI 写作</a>　<a href="/wechat-official-account">公众号创作</a>　<a href="/sticker-account">贴图号</a>　<a href="/ai-skills">AI Skill</a></nav><h1>{escape(page["h1"])}</h1><p class="lead">{escape(page["lead"])}</p><div class="grid">{sections}</div><a class="cta" href="/">进入宇宙第一工作台</a><footer>宇宙第一工作台 · 面向中文内容创作者的 AI 工作区</footer></main></body></html>'''


@router.get("/robots.txt", include_in_schema=False)
def robots() -> Response:
    return Response("User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /admin/\nSitemap: https://yuzoudiyigongzuotai.cn/sitemap.xml\n", media_type="text/plain", headers={"Cache-Control": "public, max-age=3600"})


@router.get(f"/{VERIFY_FILE}", include_in_schema=False)
def baidu_verification() -> Response:
    """Serve Baidu's ownership token at the exact root URL it verifies."""
    return Response((STATIC / VERIFY_FILE).read_text(encoding="utf-8").strip(), media_type="text/html", headers={"Cache-Control": "public, max-age=3600"})


@router.get("/sitemap.xml", include_in_schema=False)
def sitemap() -> Response:
    paths = ["/", "/ai-writing", "/wechat-official-account", "/sticker-account", "/ai-skills", "/bookshelf", "/market"]
    urls = "".join(f"<url><loc>{SITE}{path}</loc></url>" for path in paths)
    return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', media_type="application/xml", headers={"Cache-Control": "public, max-age=3600"})


def _landing(slug: str) -> HTMLResponse:
    return HTMLResponse(_page(slug), headers={"Cache-Control": "public, max-age=3600"})


@router.get("/ai-writing", response_class=HTMLResponse, include_in_schema=False)
def ai_writing() -> HTMLResponse:
    return _landing("ai-writing")


@router.get("/wechat-official-account", response_class=HTMLResponse, include_in_schema=False)
def wechat_official_account() -> HTMLResponse:
    return _landing("wechat-official-account")


@router.get("/sticker-account", response_class=HTMLResponse, include_in_schema=False)
def sticker_account() -> HTMLResponse:
    return _landing("sticker-account")


@router.get("/ai-skills", response_class=HTMLResponse, include_in_schema=False)
def ai_skills() -> HTMLResponse:
    return _landing("ai-skills")
