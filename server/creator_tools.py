"""Web adapters for Xiaohongshu, WeChat Tie-Tu, and article review Skills."""
from __future__ import annotations

import base64
import importlib.util
import json
import re
import uuid
from pathlib import Path
from typing import Any

import requests

from . import workbench
from vendor.skills.wechat_tie_tu.toolkit.tie_tu.planner import build_plan


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output" / "creator-tools"
HIT_DETECTOR_PATH = ROOT / "vendor" / "skills" / "wechat_hit_detector" / "scripts" / "detector.py"


def _load_hit_detector():
    spec = importlib.util.spec_from_file_location("vendored_wechat_hit_detector", HIT_DETECTOR_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("爆文检测 Skill 加载失败")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HIT_DETECTOR = _load_hit_detector()


def _clean_json_payload(data: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(data, ensure_ascii=False, default=str))


def xiaohongshu_package(
    topic: str,
    account: str,
    audience: str,
    goal: str,
    evidence: str,
    content_type: str,
) -> dict[str, Any]:
    evidence_state = "owned" if evidence.strip() else "unknown"
    prompt = f"""你正在执行 xiaohongshu-creator-skill 的内容包流程。请围绕主题生成一套可人工发布的小红书图文草稿。

账号定位：{account or '未提供'}
目标读者：{audience or '未提供'}
本次目标：{goal or '教育与建立信任'}
内容类型：{content_type or '自动选择'}
主题：{topic}
用户提供的自有证据：{evidence or '无。必须标记为冷启动，不得编造数据、客户、收入、经历或发布结果。'}

要求：
1. 给出3个具体、可搜索、没有夸张空泛词的标题。
2. 输出1张封面和5张内容页；每页只表达一个重点，并给出不同的人物动作。
3. 默认真人贴纸爆款教程风，3:4，人物自然，服装和脸保持一致，动作至少4种。
4. 正文包含具体步骤、完成标准、置顶评论、异议回复、低压力CTA。
5. 最多10个关键词并注明自然埋点位置。
6. 输出发布前状态 ready/revise/blocked 和最多3个优先修改。
7. 没有自有数据时只写待验证，不声称涨粉、成交或爆款。

只返回合法JSON：
{{"stage":"zero-start|starter|standard","evidence_state":"owned|unknown","angle":"...","titles":[{{"text":"...","keyword":"...","reason":"...","promise":"..."}}],"selected_title":"...","cover_copy":"...","body":"...","pinned_comment":"...","objection_reply":"...","cta":"...","keywords":[{{"word":"...","placement":"..."}}],"cards":[{{"index":1,"role":"cover","headline":"...","message":"...","action":"...","visual_prompt":"..."}}],"precheck":{{"status":"ready|revise|blocked","issues":["..."]}},"missing_evidence":["..."]}}。cards必须正好6项。"""
    data = workbench._json_text(prompt)
    cards = data.get("cards") or []
    if len(cards) != 6:
        raise workbench.ProviderError("小红书 Skill 返回的页面规划不是 6 张")
    data["session_id"] = uuid.uuid4().hex
    data["evidence_state"] = evidence_state
    data["skill"] = "xiaohongshu-creator-skill"
    return _clean_json_payload(data)


def xiaohongshu_precheck(title: str, body: str) -> dict[str, Any]:
    vague = ["天花板", "宝藏", "被问爆了", "高级感", "YYDS", "封神", "谁懂啊", "家人们"]
    promises = ["保证", "稳赚", "躺赚", "暴富", "100%", "包过"]
    issues = []
    for word in vague:
        if word.lower() in title.lower():
            issues.append(f"标题含空泛词“{word}”，请换成具体对象、步骤或场景")
    for word in promises:
        if word.lower() in f"{title}\n{body}".lower():
            issues.append(f"包含不可核验承诺“{word}”，需要删除或补充可靠证据")
    if len(title.strip()) < 8:
        issues.append("标题过短，没有清楚交代对象和读者收益")
    if len(body.strip()) < 180:
        issues.append("正文过短，尚未交付足够步骤和完成标准")
    if not re.search(r"(步骤|方法|先|再|检查|完成|清单|具体)", body):
        issues.append("正文缺少可执行步骤或完成标准")
    status = "ready" if not issues else ("blocked" if any("承诺" in item for item in issues) else "revise")
    return {"status": status, "issues": issues[:3], "checked_by": "xiaohongshu-creator-skill"}


def tie_tu_plan(
    industry: str,
    topic: str,
    title: str,
    content_type: str | None,
    image_count: int,
    style: str,
    audience: str,
    portrait_mode: str,
) -> dict[str, Any]:
    plan = build_plan(
        industry=industry,
        topic=topic,
        title=title,
        content_type=content_type or None,
        image_count=image_count,
        style=style,
        audience=audience,
        portrait_mode=portrait_mode,
    )
    prompt = f"""你正在执行 wechat-tie-tu-publisher 的卡片策划阶段。请在不改变卡片数量和角色顺序的前提下完善这份微信贴图号计划。

行业：{industry}
主题：{topic}
标题：{title or topic}
受众：{audience or '大众用户'}
内容类型：{plan.content_type_label}
视觉风格：{style or '成熟、温暖、清晰、可转发'}
卡片骨架：{json.dumps([{'index': c.index, 'role': c.role, 'purpose': c.purpose} for c in plan.cards], ensure_ascii=False)}

要求：每张只保留一个信息重点；封面主标题只保留一个承诺；所有文字适合手机阅读；不编造排名、价格、医疗、收入或效果；同一组人物保持一致但姿势、动作、场景不雷同；完整画面与准确中文标题在同一次图片生成中完成。

只返回合法JSON：{{"angle":"...","copy":"不超过300字的配套短文案","cta":"...","cards":[{{"index":1,"overlay_text":"准确中文标题","caption":"配套短句","visual_subject":"画面主体","composition":"构图与文字安全区","scene":"独立场景","action":"人物动作"}}]}}。cards必须正好{image_count}项。"""
    enriched = workbench._json_text(prompt)
    by_index = {int(item.get("index", 0)): item for item in enriched.get("cards", []) if isinstance(item, dict)}
    for card in plan.cards:
        item = by_index.get(card.index, {})
        for key in ("overlay_text", "caption", "visual_subject", "composition"):
            value = str(item.get(key) or "").strip()
            if value:
                setattr(card, key, value)
        card.card_brief.update({"scene": str(item.get("scene") or ""), "action": str(item.get("action") or "")})
    plan.angle = str(enriched.get("angle") or plan.angle)
    plan.copy = str(enriched.get("copy") or "")[:300]
    plan.cta = str(enriched.get("cta") or "")
    payload = plan.to_dict()
    payload["session_id"] = uuid.uuid4().hex
    payload["skill"] = "wechat-tie-tu-publisher"
    payload["approval_state"]["stages"]["card_plan"] = "pending_confirmation"
    return _clean_json_payload(payload)


def _decode_image(data: dict[str, Any]) -> bytes:
    items = data.get("data") or data.get("images") or []
    item = items[0] if isinstance(items, list) and items else {}
    if not item and any(data.get(key) for key in ("b64_json", "url", "image_url")):
        item = data
    if isinstance(item, dict) and item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    image_url = item.get("url") or item.get("image_url") if isinstance(item, dict) else None
    if image_url:
        response = requests.get(image_url, timeout=120)
        response.raise_for_status()
        return response.content
    raise workbench.ProviderError("图片 API 没有返回可解析的图片数据")


def generate_card_image(tool: str, session_id: str, card: dict[str, Any], style: str = "") -> dict[str, Any]:
    safe_tool = "xiaohongshu" if tool == "xiaohongshu" else "tie-tu"
    index = max(1, int(card.get("index") or 1))
    headline = str(card.get("headline") or card.get("overlay_text") or "").strip()
    prompt = f"""Use case: social media content card
Asset type: complete 3:4 vertical Chinese content card for {safe_tool}
Primary request: create card {index} as a complete finished image, with the exact Chinese title rendered inside the image.
Headline (verbatim): "{headline}"
Message: {card.get('message') or card.get('caption') or card.get('purpose') or ''}
Scene: {card.get('scene') or card.get('visual_subject') or card.get('visual_prompt') or ''}
Action: {card.get('action') or ''}
Composition: {card.get('composition') or '3:4 portrait, one visual focus, generous text-safe margins'}
Art direction: {style or 'clean, bright, polished Chinese creator editorial style'}
Consistency: keep the same fictional adult person, face, clothing logic, typography system and palette across the set, while changing pose, action, camera angle and scene for this card.
Constraints: generate image and accurate Chinese text in this one call; no border, no watermark, no logo, no QR code, no extra text, no fake metrics, no garbled text, no duplicated person, no cropped face or hands."""
    model = workbench._setting("WECHAT_IMAGE_MODEL", "gpt-image-2")
    data = workbench._post("image", "images/generations", {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": "1024x1365",
    }, timeout=420)
    data = workbench._resolve_image_response(data, timeout=420)
    raw = _decode_image(data)
    output_dir = OUTPUT_DIR / safe_tool / re.sub(r"[^a-zA-Z0-9_-]", "", session_id)[:64]
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"card-{index:02d}.png"
    output.write_bytes(raw)
    return {
        "index": index,
        "model": model,
        "bytes": output.stat().st_size,
        "url": f"/api/creator-tools/assets/{safe_tool}/{output_dir.name}/{output.name}",
        "prompt": prompt,
    }


def creator_asset(tool: str, session_id: str, filename: str) -> Path:
    safe_tool = "xiaohongshu" if tool == "xiaohongshu" else "tie-tu"
    return OUTPUT_DIR / safe_tool / Path(session_id).name / Path(filename).name


def detect_article(title: str, body: str, track: str = "auto", fans: int | None = None, open_rate: float | None = None) -> dict[str, Any]:
    forced_track = None if track == "auto" else track
    result = HIT_DETECTOR.detect(title, body, fans=fans, open_rate=open_rate, track=forced_track)
    result["suggestions"] = HIT_DETECTOR.build_suggestions(result)
    result["skill"] = "wechat-hit-detector-skill"
    return _clean_json_payload(result)


def rewrite_article(title: str, body: str, detector_result: dict[str, Any]) -> dict[str, str]:
    prompt = f"""你是公众号终审编辑。请根据 wechat-hit-detector-skill 的复核结果进行最小必要改稿。
保留文章事实、作者观点和真实经历；不新增数据、来源、案例或第一人称经历；优先解决P0/P1问题；不要为了分数机械加悬念词。

原标题：{title}
检测摘要：{json.dumps(detector_result, ensure_ascii=False)[:12000]}
原正文：
{body}

只返回合法JSON：{{"title":"修改后标题","body":"修改后完整正文","change_summary":"本次解决了什么，哪些事实仍待作者确认"}}。"""
    data = workbench._json_text(prompt)
    return {
        "title": str(data.get("title") or title),
        "body": str(data.get("body") or body),
        "change_summary": str(data.get("change_summary") or ""),
    }
