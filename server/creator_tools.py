"""Web adapters for Xiaohongshu, WeChat Tie-Tu, and article review Skills."""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import re
import uuid
from pathlib import Path
from typing import Any

import requests

from . import workbench, skill_runtime
from vendor.skills.wechat_tie_tu.toolkit.tie_tu.planner import build_plan
from vendor.skills.wechat_tie_tu.toolkit.tie_tu.models import CONTENT_TYPES


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


def _image_measurement(raw: bytes) -> dict[str, Any]:
    """Only derive technical visual facts locally; never persist the reference."""
    from PIL import Image, ImageStat
    with Image.open(io.BytesIO(raw)) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        stat = ImageStat.Stat(rgb)
        colors = rgb.quantize(colors=6).convert("RGB").getcolors(width * height) or []
        colors.sort(reverse=True)
    return {
        "dimensions": {"width": width, "height": height},
        "aspect_ratio": round(width / height, 4) if height else 0,
        "orientation": "portrait" if height > width else "landscape" if width > height else "square",
        "dominant_palette": [{"rgb": list(color), "share": round(count / (width * height), 3)} for count, color in colors[:6]],
        "brightness_mean": round(sum(stat.mean) / 3, 1),
        "contrast_stddev": round(sum(stat.stddev) / 3, 1),
    }


def viral_remix_analysis(image_data_url: str, goal: str = "") -> dict[str, Any]:
    """Analyse a user-owned reference with a vision-capable text model.

    The reference remains in request memory only. The returned brief deliberately
    excludes original copy and image pixels, so image generation starts from text.
    """
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)", image_data_url.strip())
    if not match:
        raise ValueError("请上传 PNG、JPG 或 WebP 图片")
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except ValueError as exc:
        raise ValueError("图片数据无法读取") from exc
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError("图片不能为空且不能超过 10 MB")
    try:
        measured = _image_measurement(raw)
    except Exception as exc:
        raise ValueError("图片无法解码，请换一张完整截图") from exc
    model = workbench._setting("WECHAT_TEXT_MODEL")
    if not model:
        raise workbench.ProviderError("服务端尚未配置视觉模型所用的文本 API")
    prompt = f'''你是社交媒体视觉编辑。分析用户有权发送的对标图，只提炼可迁移的结构；不要复述、引用或建议使用原图中的文案、人物、logo、IP、截图元素或任何像素。用户目标：{goal or '未补充；默认做同赛道但不同信息角度的原创内容'}。

输出严格 JSON：{{"content_guess":"主题类型","analysis":{{"visual_anchor":"第一眼看哪里","hierarchy":"文字/主体层级，不抄原文","composition":"位置、方向、留白","palette":"颜色关系","texture":"材质或光影","emotion":"情绪","hook":"停留机制","platform_language":"平台表达"}},"missing":"原图没有提供、可用来做信息增量的部分","questions":["一个最关键的确认问题"],"ideas":[{{"id":"A","name":"换素材","summary":"...","keep":"保留的抽象结构","change":"替换的素材与场景","why_original":"不撞图的原因","image_brief":"无原图元素的原创画面描述","headline":"8字以内原创标题"}},{{"id":"B","name":"换版式","summary":"...","keep":"...","change":"...","why_original":"...","image_brief":"...","headline":"..."}},{{"id":"C","name":"换角度","summary":"...","keep":"...","change":"...","why_original":"...","image_brief":"...","headline":"..."}}]}}。
必须返回 A、B、C 三项。不要声称会爆；不要生成原图文字、品牌、角色或近似画面。'''
    body = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_url, "detail": "high"}},
        ]}],
        "temperature": 0.4,
    }
    try:
        response = requests.post(workbench._api_url("text", "/chat/completions"), headers=workbench._headers("text"),
                                 json=body, timeout=120, verify=workbench._verify_ssl())
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
        raise workbench.ProviderError("视觉拆解请求失败：请确认文本模型支持图片输入后重试") from exc
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(content).strip(), flags=re.I)
    try:
        data = json.loads(cleaned[cleaned.find("{"):cleaned.rfind("}") + 1])
    except (ValueError, json.JSONDecodeError) as exc:
        raise workbench.ProviderError("视觉模型没有返回可解析的拆解结果，请重试") from exc
    ideas = data.get("ideas") if isinstance(data, dict) else None
    if not isinstance(ideas, list) or [item.get("id") for item in ideas if isinstance(item, dict)] != ["A", "B", "C"]:
        raise workbench.ProviderError("视觉模型没有返回完整的 A/B/C 翻新方案，请重试")
    data["measurement"] = measured
    data["skill"] = "tietu-refresh"
    return _clean_json_payload(data)


def generate_viral_remix_image(session_id: str, idea: dict[str, Any]) -> dict[str, Any]:
    """Generate only from the approved text brief, never from the reference image."""
    card = {
        "index": 1,
        "headline": str(idea.get("headline") or "").strip(),
        "caption": str(idea.get("summary") or "").strip(),
        "visual_subject": str(idea.get("image_brief") or "").strip(),
        "composition": "3:4 portrait, one original visual focus, generous text-safe margins",
    }
    if not card["headline"] or not card["visual_subject"]:
        raise ValueError("请选择一套完整的翻新方案后再生成")
    return generate_card_image("viral-remix", session_id, card, "original social-media editorial image; do not use any reference-image elements")


def xiaohongshu_package(
    topic: str,
    account: str,
    audience: str,
    goal: str,
    evidence: str,
    content_type: str,
    image_count: int = 6,
    requirements: str = '',
) -> dict[str, Any]:
    if isinstance(image_count, bool) or not isinstance(image_count, int) or not 0 <= image_count <= 12:
        raise ValueError('图片数量需要在 0 到 12 之间')
    instructions, _ = skill_runtime.context(ROOT / 'vendor/skills/xiaohongshu_creator')
    evidence_state = "owned" if evidence.strip() else "unknown"
    prompt = f"""{instructions}

请围绕主题生成一套可人工发布的小红书草稿。
用户后续要求：{requirements or '无'}

账号定位：{account or '未提供'}
目标读者：{audience or '未提供'}
本次目标：{goal or '教育与建立信任'}
内容类型：{content_type or '自动选择'}
主题：{topic}
用户提供的自有证据：{evidence or '无。必须标记为冷启动，不得编造数据、客户、收入、经历或发布结果。'}

要求：
1. 给出3个具体、可搜索、没有夸张空泛词的标题。
2. 输出{image_count}张卡片，数量为0时只输出文字、cards为空数组；否则第一张为封面，其余为内容页，每页只表达一个重点。
3. 默认真人贴纸爆款教程风，3:4，人物自然，服装和脸保持一致，动作至少4种。
4. 正文包含具体步骤、完成标准、置顶评论、异议回复、低压力CTA。
5. 最多10个关键词并注明自然埋点位置。
6. 输出发布前状态 ready/revise/blocked 和最多3个优先修改。
7. 没有自有数据时只写待验证，不声称涨粉、成交或爆款。

只返回合法JSON：
{{"stage":"zero-start|starter|standard","evidence_state":"owned|unknown","angle":"...","titles":[{{"text":"...","keyword":"...","reason":"...","promise":"..."}}],"selected_title":"...","cover_copy":"...","body":"...","pinned_comment":"...","objection_reply":"...","cta":"...","keywords":[{{"word":"...","placement":"..."}}],"cards":[{{"index":1,"role":"cover","headline":"...","message":"...","action":"...","visual_prompt":"..."}}],"precheck":{{"status":"ready|revise|blocked","issues":["..."]}},"missing_evidence":["..."]}}。cards必须正好{image_count}项。"""
    data = workbench._json_text(prompt)
    cards = data.get("cards") or []
    if len(cards) != image_count:
        raise workbench.ProviderError(f"小红书返回的页面规划不是 {image_count} 张")
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
    requirements: str = '',
) -> dict[str, Any]:
    instructions, _ = skill_runtime.context(ROOT / 'vendor/skills/wechat_tie_tu')
    if image_count == 0:
        data = workbench._json_text(f'''{instructions}
用户这次只需要配套文案，不需要卡片或图片。不要进入图片阶段。
主题：{topic}
标题：{title}
受众：{audience}
风格：{style}
补充要求：{requirements}
只返回JSON：{{"copy":"完整文案","cta":"可选结尾"}}''')
        return {'session_id': uuid.uuid4().hex, 'title': title or topic,
                'copy': str(data.get('copy') or ''), 'cta': str(data.get('cta') or ''),
                'cards': [], 'content_type_label': '纯文案', 'angle': '', 'ratio': ''}
    # The model may return the human-readable label shown in the UI; the
    # planner consumes canonical IDs. Map only exact supported labels.
    requested_type = (content_type or '').strip()
    content_type = {label: key for key, label in CONTENT_TYPES.items()}.get(requested_type, requested_type) or None
    portrait_mode = (portrait_mode or '').strip() or 'auto'
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
    prompt = f"""{instructions}
请在不改变卡片数量和角色顺序的前提下完善这份微信贴图号计划。

行业：{industry}
主题：{topic}
标题：{title or topic}
受众：{audience or '大众用户'}
内容类型：{plan.content_type_label}
视觉风格：{style or '成熟、温暖、清晰、可转发'}
补充要求：{requirements}
人物约束：{'允许按用户要求安排人物并保持一致' if plan.portrait_enabled else '画面不能出现人物、人体、人脸或人群；使用无人物的物品与环境，action 描述物件状态，不描写人物动作'}。
卡片骨架：{json.dumps([{'index': c.index, 'role': c.role, 'purpose': c.purpose} for c in plan.cards], ensure_ascii=False)}

要求：每张只保留一个信息重点；封面主标题只保留一个承诺；所有文字适合手机阅读；不编造排名、价格、医疗、收入或效果；{'同一组人物保持一致但姿势、动作、场景不雷同' if plan.portrait_enabled else '场景与物件各有变化，不出现人物'}；完整画面与准确中文标题在同一次图片生成中完成。

只返回合法JSON：{{"angle":"...","copy":"不超过300字的配套短文案","cta":"...","cards":[{{"index":1,"overlay_text":"准确中文标题","caption":"配套短句","visual_subject":"画面主体","composition":"构图与文字安全区","scene":"独立场景","action":"人物动作"}}]}}。cards必须正好{image_count}项。"""
    enriched = workbench._json_text(prompt)
    rows = enriched.get('cards')
    if not isinstance(rows, list) or len(rows) != image_count or any(not isinstance(item, dict) or type(item.get('index')) is not int for item in rows):
        raise workbench.ProviderError('贴图计划的卡片数量或序号不完整，请重试')
    by_index = {item['index']: item for item in rows}
    if set(by_index) != set(range(1, image_count + 1)):
        raise workbench.ProviderError('贴图计划的卡片序号不完整或重复，请重试')
    if any(not str(item.get(key) or '').strip() for item in rows for key in ('overlay_text', 'caption', 'visual_subject', 'composition')):
        raise workbench.ProviderError('贴图计划缺少卡片文字或画面说明，请重试')
    if not plan.portrait_enabled:
        # Detect explicit person descriptions while allowing an instruction such
        # as “无人物”. This is a conservative clue, not image-content proof.
        def has_person(item):
            description = ' '.join(str(item.get(key) or '') for key in ('visual_subject', 'scene', 'action'))
            description = re.sub(r'(?:无|不含|没有|不要|不出现|避免|排除)\s*(?:任何)?\s*(?:人物|人像|人体|人脸|人群|模特)', '', description)
            return bool(re.search(r'人物|人像|人体|人脸|人群|女性|男性|模特|女人|男人|女孩|男孩|女士|先生|夫妻|手部|一双手|手掌|手指|人物背影', description))
        conflicts = [item for item in rows if has_person(item)]
        if conflicts:
            repair = workbench._json_text('用户明确要求画面不出现人物。仅修复下列卡片的 visual_subject、scene 和 action；'
                '使用合适的物品及环境，不出现人物、人体、脸或人群，不修改标题和配套文案。'
                '返回JSON {"cards":[{"index":1,"visual_subject":"无人物画面","scene":"环境","action":"物件状态"}]}。\n'
                + json.dumps([{'index': item['index'], 'overlay_text': item['overlay_text'],
                               'caption': item['caption']} for item in conflicts], ensure_ascii=False))
            repaired = repair.get('cards') if isinstance(repair, dict) else None
            if not isinstance(repaired, list) or len(repaired) != len(conflicts):
                raise workbench.ProviderError('用户选择不使用人物，但计划仍含人物画面；请重试')
            replacements = {item.get('index'): item for item in repaired if isinstance(item, dict) and type(item.get('index')) is int}
            if set(replacements) != {item['index'] for item in conflicts}:
                raise workbench.ProviderError('无人物画面修正的卡片序号不完整；请重试')
            for item in conflicts:
                replacement = replacements[item['index']]
                if not str(replacement.get('visual_subject') or '').strip():
                    raise workbench.ProviderError('无人物画面修正缺少画面主体；请重试')
                for key in ('visual_subject', 'scene', 'action'):
                    item[key] = str(replacement.get(key) or '').strip()
            if any(has_person(item) for item in conflicts):
                raise workbench.ProviderError('用户选择不使用人物，但计划仍含人物画面；请重试')
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


def generate_card_image(tool: str, session_id: str, card: dict[str, Any], style: str = "", *, size: str = '768x1024') -> dict[str, Any]:
    if not re.fullmatch(r'\d{3,4}x\d{3,4}', size) or not all(256 <= int(n) <= 4096 and int(n) % 16 == 0 for n in size.split('x')):
        raise ValueError('尺寸须为像素宽x高，宽高256到4096且为16的倍数，例如768x1024（3:4）或720x1280（9:16）')
    safe_tool = "xiaohongshu" if tool == "xiaohongshu" else "tie-tu"
    index = max(1, int(card.get("index") or 1))
    headline = str(card.get("headline") or card.get("overlay_text") or "").strip()
    no_people = safe_tool == 'tie-tu' and card.get('portrait_enabled') is False
    consistency = ('Do not depict people, faces, body parts or crowds; use objects and environments only.' if no_people else
                   'Keep the same fictional adult person, face and clothing logic when a person is requested; keep typography and palette consistent.')
    prompt = f"""Use case: social media content card
Asset type: complete Chinese content card for {safe_tool}, size {size}
Primary request: create card {index} as a complete finished image, with the exact Chinese title rendered inside the image.
Headline (verbatim): "{headline}"
Message: {card.get('message') or card.get('caption') or card.get('purpose') or ''}
Scene: {card.get('scene') or card.get('visual_subject') or card.get('visual_prompt') or ''}
Action: {card.get('action') or ''}
Composition: {card.get('composition') or '3:4 portrait, one visual focus, generous text-safe margins'}
Art direction: {style or 'clean, bright, polished Chinese creator editorial style'}
Consistency: {consistency}
Constraints: generate image and accurate Chinese text in this one call; no border, no watermark, no logo, no QR code, no extra text, no fake metrics, no garbled text, no duplicated person, no cropped face or hands."""
    model = workbench._setting("WECHAT_IMAGE_MODEL", "gpt-image-2")
    from . import image_provider
    data = image_provider.generate({
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
    })
    raw = _decode_image(data)
    from PIL import Image
    try:
        with Image.open(io.BytesIO(raw)) as decoded:
            decoded.load()
            dimensions = decoded.size
    except Exception as exc:
        raise workbench.ProviderError('图片接口返回的内容无法解码，未保存为成功图片') from exc
    output_dir = OUTPUT_DIR / safe_tool / re.sub(r"[^a-zA-Z0-9_-]", "", session_id)[:64]
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"card-{index:02d}.png"
    output.write_bytes(raw)
    return {
        "index": index,
        "bytes": output.stat().st_size,
        "width": dimensions[0], "height": dimensions[1],
        "url": f"/api/creator-tools/assets/{safe_tool}/{output_dir.name}/{output.name}",
        "prompt": prompt,
    }


def creator_asset(tool: str, session_id: str, filename: str) -> Path:
    safe_tool = "xiaohongshu" if tool == "xiaohongshu" else "tie-tu"
    return OUTPUT_DIR / safe_tool / Path(session_id).name / Path(filename).name


def morning_draft(topic, image_count=4, copy_count=3, style='', mode='article', columns=1,
                  image_at=1, image_position='after', size='768x1024', requirements=''):
    for name, value, low, high in [('image_count', image_count, 0, 8), ('copy_count', copy_count, 1, 8),
                                  ('columns', columns, 1, 4), ('image_at', image_at, 1, 8)]:
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{name}超出允许范围')
    if mode not in {'article', 'sticker'} or image_position not in {'before', 'after'}:
        raise ValueError('排版模式错误')
    if not re.fullmatch(r'\d{3,4}x\d{3,4}', size) or not all(256 <= int(n) <= 4096 and int(n) % 16 == 0 for n in size.split('x')):
        raise ValueError('尺寸须为像素宽x高，宽高256到4096且为16的倍数，例如768x1024（3:4）或720x1280（9:16）')
    instructions, _ = skill_runtime.context(ROOT / 'vendor/skills/morning_blessing')
    result = workbench._json_text(f'''{instructions}
生成本次文案与图片计划，不声称已生成图片。
主题：{topic}；风格：{style}；补充要求：{requirements}
文案{copy_count}条，图片计划{image_count}张，尺寸{size}。
只返回JSON：{{"title":"标题","copies":["文案"],"cards":[{{"index":1,"headline":"早安","message":"图片祝福文字","scene":"场景","action":"动作","composition":"构图"}}]}}。
cards必须正好{image_count}项，copies必须正好{copy_count}项。''')
    if len(result.get('cards', [])) != image_count or len(result.get('copies', [])) != copy_count:
        raise workbench.ProviderError('返回的文案或图片计划数量不符')
    if not all(isinstance(item, str) and item.strip() for item in result['copies']):
        raise workbench.ProviderError('文案格式错误')
    for index, card in enumerate(result['cards'], 1):
        if not isinstance(card, dict):
            raise workbench.ProviderError('图片计划格式错误')
        card['index'] = index
        if '早安' not in str(card.get('headline', '')):
            card['headline'] = '早安 ' + str(card.get('headline', ''))
    result.update(session_id=uuid.uuid4().hex, mode=mode, columns=columns,
                  image_at=image_at, image_position=image_position, size=size)
    return result


def detect_article(title: str, body: str, track: str = "auto", fans: int | None = None, open_rate: float | None = None) -> dict[str, Any]:
    forced_track = None if track == "auto" else track
    result = HIT_DETECTOR.detect(title, body, fans=fans, open_rate=open_rate, track=forced_track)
    result["suggestions"] = HIT_DETECTOR.build_suggestions(result)
    result["skill"] = "wechat-hit-detector-skill"
    return _clean_json_payload(result)


def rewrite_article(title: str, body: str, detector_result: dict[str, Any]) -> dict[str, str]:
    instructions, _ = skill_runtime.context(ROOT / 'vendor/skills/wechat_hit_detector',
        ('references/official-rules-evidence.md', 'references/platform-rules.md',
         'references/platform-rules-basic.md'))
    prompt = f"""{instructions}

你是公众号终审编辑。请根据复核结果进行最小必要改稿。
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
