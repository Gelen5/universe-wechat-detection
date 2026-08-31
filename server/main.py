import contextlib
import io
import json
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import wechat_analyzer as analyzer
from . import accounts
from . import creator_tools
from . import workbench


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
ANALYZER_LOCK = threading.RLock()
WORKBENCH_JOB_LOCK = threading.RLock()
WORKBENCH_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="workbench")

app = FastAPI(
    title="公众号账号诊断",
    description="公众号数据诊断与可视化报告",
    version="1.0.0",
)

accounts.init_db()
accounts.recover_interrupted_workbench_jobs()


@app.middleware("http")
async def disable_frontend_cache(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.middleware("http")
async def account_and_points_gate(request: Request, call_next):
    """Protect product APIs and settle all point charges in one place."""
    path = request.url.path
    public_api = path in {"/api/auth/register", "/api/auth/login"}
    user = accounts.user_from_request(request)
    request.state.user = user
    if path.startswith("/api/") and not public_api and not user:
        return JSONResponse(status_code=401, content={"detail": "请先登录"})

    # The long-running full workbench owns billing in its background job so a
    # later provider failure can refund points after the HTTP response returned.
    rule = accounts.pricing_rule(request.method, path) if user and path != "/api/workbench/sessions" else None
    usage_id = None
    started = time.perf_counter()
    if rule:
        try:
            usage_id = accounts.reserve_points(user["id"], rule, request.method, path)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    try:
        response = await call_next(request)
    except Exception:
        if usage_id:
            accounts.refund_usage(usage_id, 500, int((time.perf_counter() - started) * 1000))
        raise

    if usage_id:
        duration = int((time.perf_counter() - started) * 1000)
        if response.status_code < 400:
            accounts.settle_usage(usage_id, response.status_code, duration)
            response.headers["X-Points-Charged"] = str(rule["points"])
        else:
            accounts.refund_usage(usage_id, response.status_code, duration)
            response.headers["X-Points-Refunded"] = str(rule["points"])
        response.headers["X-Points-Balance"] = str(accounts.wallet_summary(user["id"])["balance"])
    return response


class DiagnoseRequest(BaseModel):
    account_name: str = Field(min_length=1, max_length=80)
    textApiKey: str | None = Field(default=None, max_length=300)


class WorkbenchCreateRequest(BaseModel):
    topic: str = Field(default="", max_length=240)
    mode: str = Field(default="interactive", pattern="^(auto|interactive|single)$")
    persona: str = Field(default="深度观察者", max_length=80)
    theme: str = Field(default="default", max_length=80)
    textApiKey: str | None = Field(default=None, max_length=300)
    imageApiKey: str | None = Field(default=None, max_length=300)
    textBaseUrl: str | None = Field(default=None, max_length=300)
    imageBaseUrl: str | None = Field(default=None, max_length=300)
    textModel: str | None = Field(default=None, max_length=120)
    imageModel: str | None = Field(default=None, max_length=120)
    idempotency_key: str = Field(min_length=8, max_length=120)


class WorkbenchStepRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=80)
    step: int = Field(ge=1, le=8)
    selection: int | None = Field(default=None, ge=1, le=10)
    article: str | None = Field(default=None, max_length=200000)
    textApiKey: str | None = Field(default=None, max_length=300)
    imageApiKey: str | None = Field(default=None, max_length=300)
    textBaseUrl: str | None = Field(default=None, max_length=300)
    imageBaseUrl: str | None = Field(default=None, max_length=300)
    textModel: str | None = Field(default=None, max_length=120)
    imageModel: str | None = Field(default=None, max_length=120)


class WorkbenchPreviewRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=80)
    article: str | None = Field(default=None, max_length=200000)
    textApiKey: str | None = Field(default=None, max_length=300)
    imageApiKey: str | None = Field(default=None, max_length=300)
    textBaseUrl: str | None = Field(default=None, max_length=300)
    imageBaseUrl: str | None = Field(default=None, max_length=300)
    textModel: str | None = Field(default=None, max_length=120)
    imageModel: str | None = Field(default=None, max_length=120)


class WorkbenchPublishRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=80)
    draft: bool = True
    textApiKey: str | None = Field(default=None, max_length=300)
    imageApiKey: str | None = Field(default=None, max_length=300)
    textBaseUrl: str | None = Field(default=None, max_length=300)
    imageBaseUrl: str | None = Field(default=None, max_length=300)
    textModel: str | None = Field(default=None, max_length=120)
    imageModel: str | None = Field(default=None, max_length=120)


class ImageGenerationRequest(BaseModel):
    apiKey: str | None = Field(default=None, max_length=300)
    baseUrl: str = Field(default="https://img.rjm.us.ci", max_length=300)
    model: str = Field(default="gpt-image-2", max_length=80)
    prompt: str = Field(min_length=1, max_length=20000)
    size: str = Field(default="1024x1365", max_length=40)
    n: int = Field(default=1, ge=1, le=4)


class ProviderTestRequest(BaseModel):
    kind: str = Field(pattern="^(text|image)$")
    textApiKey: str | None = Field(default=None, max_length=300)
    imageApiKey: str | None = Field(default=None, max_length=300)
    textBaseUrl: str | None = Field(default=None, max_length=300)
    imageBaseUrl: str | None = Field(default=None, max_length=300)
    textModel: str | None = Field(default=None, max_length=120)
    imageModel: str | None = Field(default=None, max_length=120)


class ProviderSettingsRequest(BaseModel):
    text_api_key: str = Field(default="", max_length=300)
    image_api_key: str = Field(default="", max_length=300)
    text_base_url: str = Field(default="", max_length=300)
    image_base_url: str = Field(default="", max_length=300)
    text_model: str = Field(default="", max_length=120)
    image_model: str = Field(default="", max_length=120)


class AuthRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class RegisterRequest(AuthRequest):
    display_name: str = Field(default="", max_length=40)


class RechargeRequest(BaseModel):
    user_id: str = Field(min_length=16, max_length=64)
    points: int = Field(ge=1, le=1_000_000)
    bucket: str = Field(default="trial", pattern="^(trial|bonus|paid)$")
    note: str = Field(min_length=1, max_length=300)


class ImpersonateRequest(BaseModel):
    user_id: str = Field(min_length=16, max_length=64)


class XiaohongshuRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=300)
    account: str = Field(default="", max_length=300)
    audience: str = Field(default="", max_length=200)
    goal: str = Field(default="教育与建立信任", max_length=120)
    evidence: str = Field(default="", max_length=12000)
    contentType: str = Field(default="自动选择", max_length=80)
    textApiKey: str | None = Field(default=None, max_length=300)
    imageApiKey: str | None = Field(default=None, max_length=300)
    textBaseUrl: str | None = Field(default=None, max_length=300)
    imageBaseUrl: str | None = Field(default=None, max_length=300)
    textModel: str | None = Field(default=None, max_length=120)
    imageModel: str | None = Field(default=None, max_length=120)


class TieTuPlanRequest(BaseModel):
    industry: str = Field(default="生活方式", max_length=120)
    topic: str = Field(min_length=2, max_length=300)
    title: str = Field(default="", max_length=120)
    contentType: str = Field(default="", max_length=80)
    imageCount: int = Field(default=5, ge=1, le=12)
    style: str = Field(default="", max_length=400)
    audience: str = Field(default="", max_length=200)
    portraitMode: str = Field(default="auto", pattern="^(auto|required|off)$")
    textApiKey: str | None = Field(default=None, max_length=300)
    imageApiKey: str | None = Field(default=None, max_length=300)
    textBaseUrl: str | None = Field(default=None, max_length=300)
    imageBaseUrl: str | None = Field(default=None, max_length=300)
    textModel: str | None = Field(default=None, max_length=120)
    imageModel: str | None = Field(default=None, max_length=120)


class CreatorImageRequest(BaseModel):
    tool: str = Field(pattern="^(xiaohongshu|tie-tu)$")
    sessionId: str = Field(min_length=8, max_length=80)
    card: dict[str, Any]
    style: str = Field(default="", max_length=500)
    textApiKey: str | None = Field(default=None, max_length=300)
    imageApiKey: str | None = Field(default=None, max_length=300)
    textBaseUrl: str | None = Field(default=None, max_length=300)
    imageBaseUrl: str | None = Field(default=None, max_length=300)
    textModel: str | None = Field(default=None, max_length=120)
    imageModel: str | None = Field(default=None, max_length=120)


class HitDetectorRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=200000)
    track: str = Field(default="auto", pattern="^(auto|tech|finance|workplace|health|education|relationship|food|beauty|realestate|senior|general)$")
    fans: int | None = Field(default=None, ge=0)
    openRate: float | None = Field(default=None, ge=0, le=100)


class HitRewriteRequest(HitDetectorRequest):
    detectorResult: dict[str, Any] = Field(default_factory=dict)
    textApiKey: str | None = Field(default=None, max_length=300)
    imageApiKey: str | None = Field(default=None, max_length=300)
    textBaseUrl: str | None = Field(default=None, max_length=300)
    imageBaseUrl: str | None = Field(default=None, max_length=300)
    textModel: str | None = Field(default=None, max_length=120)
    imageModel: str | None = Field(default=None, max_length=120)


def _last_json_line(output: str):
    for line in reversed(output.splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    return None


def _num(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _work_text(work):
    return str(work.get("标题") or work.get("title") or "").strip()


def _topic_signature(titles):
    """Extract a short, evidence-bound topic label from returned titles."""
    groups = [
        ("车型、价格和对比", ("价格", "元", "对比", "怎么选", "配置", "换代", "车型", "新车", "四缸", "摩托")),
        ("工具、效率和方法", ("工具", "效率", "自动化", "教程", "方法", "实测", "AI")),
        ("关系、情绪和处境", ("感情", "关系", "爱", "分手", "情绪", "孤独", "婚姻", "恋爱")),
        ("职场、工作和成长", ("职场", "工作", "面试", "领导", "副业", "创业", "成长")),
        ("消费、产品和购买判断", ("测评", "推荐", "购买", "体验", "产品", "价格", "优惠")),
    ]
    scores = [(label, sum(1 for title in titles for word in words if word.lower() in title.lower())) for label, words in groups]
    label, hits = max(scores, key=lambda item: item[1], default=("近期内容", 0))
    return label if hits else "近期内容"


def _time_value(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _dynamic_recommendations(header, scores, works, dimensions, avg_read, interaction_rate):
    """Turn the Redfox evidence into account-specific actions.

    This intentionally stays deterministic and evidence-bound: no diagnosis
    sentence or route card is selected from a global fixed list.
    """
    name = header.get("账号名") or "这个账号"
    titles = [_work_text(work) for work in works if _work_text(work)]
    title_lengths = [len(title) for title in titles]
    avg_title_length = sum(title_lengths) / len(title_lengths) if title_lengths else 0
    latest = _time_value(works[0].get("发布时间")) if works else None
    oldest = _time_value(works[-1].get("发布时间")) if works else None
    span_days = (latest - oldest).days if latest and oldest else 0
    top_title = titles[0] if titles else "暂无有效标题"
    topic = _topic_signature(titles)
    weakest = min(dimensions, key=lambda item: item["score"]) if dimensions else {"name": "数据", "score": 0}
    weakest_name = weakest["name"]
    sample = len(works)

    highest_read = int(max([_num(work.get("阅读数")) for work in works] or [0]))
    comment_count = int(sum(_num(work.get("评论数")) for work in works))
    if not works:
        diagnosis = {
            "headline": f"{name}目前还没有足够内容样本",
            "evidence": "当前没有可分析的近期作品，暂时不能判断内容方向、传播表现和用户反馈。",
            "action": "先积累至少 5 篇同口径作品，再开始判断主题和数据变化。",
        }
    elif weakest_name == "用户活跃度" or interaction_rate < 1:
        diagnosis = {
            "headline": f"{topic}方向已经出现，但用户还没有被带入判断",
            "evidence": f"近期 {sample} 篇作品平均阅读 {int(avg_read)}，评论 {comment_count} 条，互动率 {interaction_rate:.1f}%；内容被看见后，回应没有跟上。",
            "action": f"围绕《{top_title[:24]}》这类高阅读选题，下一篇加入一个具体的二选一问题，让读者有明确的回应入口。",
        }
    elif weakest_name == "内容核心数据表现" or avg_read < 1000:
        diagnosis = {
            "headline": f"{topic}选题已经成形，但传播效率还没有跑起来",
            "evidence": f"近期 {sample} 篇作品平均阅读 {int(avg_read)}，最高 {highest_read}，单篇表现仍主要依赖偶然的选题和标题。",
            "action": f"拆解《{top_title[:24]}》的主题、标题和发布时间，连续做 3 篇同场景变体，验证能否复制阅读表现。",
        }
    elif weakest_name == "内容健康度":
        diagnosis = {
            "headline": f"{topic}内容有样本，但主题还没有收窄",
            "evidence": f"当前有 {sample} 篇近期作品，标题主题分散，内容健康度为 {weakest['score']:.1f} 分，长期方向仍需要同类样本验证。",
            "action": f"先围绕《{top_title[:24]}》代表的场景连续发布，不要同时扩大到新的内容方向。",
        }
    elif weakest_name == "运营规范性":
        diagnosis = {
            "headline": f"{topic}基础已经具备，但发布节奏还不够稳定",
            "evidence": f"近期只有 {sample} 篇可比较作品，运营规范性为 {weakest['score']:.1f} 分，暂时难以判断固定时段的真实效果。",
            "action": "固定一个发布日和时段连续执行 4 周，再比较主题、发布时间和阅读反馈。",
        }
    else:
        diagnosis = {
            "headline": f"{topic}已经有基础，下一步要验证什么能够复制",
            "evidence": f"当前综合评分 {float(scores.get('综合评分') or 0):.1f} 分，最低维度为{weakest_name}，已有 {sample} 篇作品可以继续做对照。",
            "action": f"以《{top_title[:24]}》为样本，保持主题不变，只调整一个变量后继续发布。",
        }
    verdict = diagnosis["headline"]

    routes = []
    if weakest_name == "用户活跃度" or interaction_rate < 1:
        routes.append({
            "priority": "紧急",
            "title": f"围绕《{top_title[:18]}》设计一个回应入口",
            "evidence": f"近期样本互动率 {interaction_rate:.1f}%，点赞、评论和在看合计反馈有限。",
            "action": "下一篇只设置一个具体问题，并把问题放在正文结尾或标题承诺之后，连续观察回应变化。",
            "target": "成功信号：互动率较当前基线提高，并出现稳定评论或在看反馈。",
        })
    if weakest_name == "内容核心数据表现" or avg_read <= 1000:
        routes.append({
            "priority": "紧急",
            "title": "复用阅读最高的内容结构",
            "evidence": f"当前平均阅读约 {int(avg_read)}，样本中最高阅读为 {int(max([_num(w.get('阅读数')) for w in works] or [0]))}。",
            "action": f"以《{top_title[:22]}》的主题、标题长度和发布时段为参照，连续做 3 个同场景变体。",
            "target": "成功信号：同一内容结构出现至少 2 次高于账号平均阅读的作品。",
        })
    if weakest_name == "内容健康度" or avg_title_length < 12:
        routes.append({
            "priority": "重点",
            "title": "从近期标题中提炼一个可重复栏目",
            "evidence": f"当前返回的 {sample} 个标题平均长度约 {avg_title_length:.1f} 字，主题稳定性需要继续验证。",
            "action": "把高频对象、场景或情绪词组合成固定栏目名，接下来连续发布同一场景，不要每篇更换定位。",
            "target": "成功信号：连续作品标题都能被归入同一主题，且阅读波动收窄。",
        })
    if weakest_name == "运营规范性" or span_days > 0 and sample < 5:
        routes.append({
            "priority": "重点",
            "title": "按近期发布时间建立发布节奏",
            "evidence": f"当前可见 {sample} 篇作品，时间跨度约 {span_days} 天，更新节奏仍需形成样本。",
            "action": "选择一个固定发布日和时段，连续执行 4 周，并记录每篇发布后 24 小时的数据。",
            "target": "成功信号：每周都有稳定发布，能比较不同主题和时段的表现。",
        })
    routes.append({
        "priority": "持续",
        "title": "建立一张真实数据复盘卡",
        "evidence": f"本次返回 {sample} 篇作品，已知总阅读 {int(sum(_num(w.get('阅读数')) for w in works))}，互动率 {interaction_rate:.1f}%。",
        "action": "每周记录标题、发布时间、阅读、点赞、评论和在看，只保留有数据证据的主题结论。",
        "target": "成功信号：累计更多同口径样本后，能明确下一周继续什么、停止什么。",
    })
    return routes[:5], verdict, diagnosis


def _public_text(value):
    """Remove provider branding from all user-facing report text."""
    if isinstance(value, str):
        return value.replace("红狐", "数据接口")
    if isinstance(value, list):
        return [_public_text(item) for item in value]
    if isinstance(value, dict):
        return {key: _public_text(item) for key, item in value.items()}
    return value


def _enrich_report(report):
    """Add decision-friendly evidence for the visual report page.

    The original Skill intentionally returns a compact, agent-friendly JSON
    document. The web product needs a second layer: explain what the score
    means, show the evidence behind it, and turn weak signals into actions.
    """
    header = report.get("header", {})
    scores = report.get("scores", {})
    works = report.get("works", []) or []
    reads = [_num(work.get("阅读数")) for work in works]
    likes = sum(_num(work.get("点赞数")) for work in works)
    comments = sum(_num(work.get("评论数")) for work in works)
    watch = sum(_num(work.get("在看数")) for work in works)
    total_reads = sum(reads)
    interaction_rate = ((likes + comments + watch) / total_reads * 100) if total_reads else 0
    avg_read = _num(header.get("平均阅读数")) or (sum(reads) / len(reads) if reads else 0)
    overall = _num(scores.get("综合评分"))
    last_publish = works[0].get("发布时间") if works else None

    dimension_defs = [
        ("内容健康度", "内容是否稳定、垂直、具备持续生产能力", scores.get("内容健康度得分")),
        ("用户活跃度", "读者是否愿意点赞、评论、分享和参与", scores.get("用户活跃度得分")),
        ("核心数据表现", "作品是否获得真实曝光和互动反馈", scores.get("内容核心数据表现得分")),
        ("运营规范性", "更新节奏、发布时间和账号基础是否完整", scores.get("运营规范性得分")),
    ]
    dimensions = []
    for name, description, raw_score in dimension_defs:
        value = _num(raw_score)
        status = "优势项" if value >= 70 else ("观察项" if value >= 50 else "优先修复")
        dimensions.append({"name": name, "description": description, "score": value, "status": status})

    recommendations, verdict, diagnosis = _dynamic_recommendations(
        header, scores, works, dimensions, avg_read, interaction_rate
    )
    highest_work = max(works, key=lambda work: _num(work.get("阅读数")), default={})
    lowest_work = min(works, key=lambda work: _num(work.get("阅读数")), default={})
    top_dimensions = sorted(dimensions, key=lambda item: item["score"], reverse=True)
    low_dimensions = sorted(dimensions, key=lambda item: item["score"])
    industry = scores.get("行业对标", {}) or {}
    overview_judgment = (
        f"账号已经持续更新，但当前平均阅读约 {int(avg_read)}，内容尚未转化成稳定的阅读和互动。"
        if works and avg_read < 1000
        else f"账号已有 {len(works)} 篇近期作品，下一步应围绕数据表现最好的主题继续验证。"
    )
    strengths = [
        f"{top_dimensions[0]['name']}得分 {top_dimensions[0]['score']:.1f}，是当前相对稳定的基础。",
        f"近期保持 {len(works)} 篇作品样本，最高阅读为 {int(_num(highest_work.get('阅读数')))}。",
    ] if works and top_dimensions else []
    weaknesses = [
        f"{low_dimensions[0]['name']}得分 {low_dimensions[0]['score']:.1f}，是当前最需要优先修复的维度。",
        f"最高阅读 {int(_num(highest_work.get('阅读数')))}、最低阅读 {int(_num(lowest_work.get('阅读数')))}，单篇表现波动明显。",
    ] if works and low_dimensions else ["当前样本不足，暂时不能判断长期方向。"]

    report["web_insights"] = {
        "verdict": verdict,
        "diagnosis": diagnosis,
        "summary": f"本次判断基于 {len(works)} 篇近期作品、平均阅读 {int(avg_read)} 和 {interaction_rate:.1f}% 互动率；当前最低维度为 {min(dimensions, key=lambda item: item['score'])['name'] if dimensions else '暂无'}。",
        "overview_judgment": overview_judgment,
        "sample_size": len(works),
        "avg_read": int(avg_read),
        "total_reads": int(total_reads),
        "highest_read": int(_num(highest_work.get("阅读数"))),
        "lowest_read": int(_num(lowest_work.get("阅读数"))),
        "likes": int(likes),
        "comments": int(comments),
        "watch": int(watch),
        "interaction_rate": round(interaction_rate, 1),
        "last_publish": last_publish or "暂无",
        "dimensions": dimensions,
        "recommendations": recommendations,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "benchmark": {
            "overall": industry.get("综合评分", {}),
            "average_read": industry.get("平均阅读量", {}),
            "interaction": industry.get("互动率", {}),
            "frequency": industry.get("更新频率", {}),
        },
        "confidence": "低" if len(works) < 5 else ("中" if len(works) < 10 else "高"),
    }
    return _public_text(report)


@app.get("/health")
def health():
    return {"status": "ok", "service": "wechat-account-detection"}


@app.post("/api/auth/register")
def register_account(payload: RegisterRequest, response: Response):
    user = accounts.register(payload.email, payload.password, payload.display_name)
    accounts.create_session(user["id"], response)
    return {"status": "success", "user": user, "wallet": accounts.wallet_summary(user["id"])}


@app.post("/api/auth/login")
def login_account(payload: AuthRequest, response: Response):
    user = accounts.authenticate(payload.email, payload.password)
    accounts.create_session(user["id"], response)
    return {"status": "success", "user": user, "wallet": accounts.wallet_summary(user["id"])}


@app.post("/api/auth/logout")
def logout_account(request: Request, response: Response):
    accounts.revoke_session(request, response)
    return {"status": "success"}


@app.get("/api/auth/me")
def current_account(request: Request):
    user = accounts.require_user(request)
    return {"status": "success", "user": user, "wallet": accounts.wallet_summary(user["id"])}


@app.get("/api/wallet")
def get_wallet(request: Request):
    user = accounts.require_user(request)
    return {
        "status": "success",
        "wallet": accounts.wallet_summary(user["id"]),
        "transactions": accounts.list_transactions(user["id"]),
    }


@app.get("/api/pricing")
def get_pricing(request: Request):
    accounts.require_user(request)
    return {"status": "success", "rules": accounts.list_pricing(), "currency": "points", "face_value_cny": 0.1}


@app.get("/api/admin/users")
def admin_users(request: Request, query: str = ""):
    accounts.require_admin(request)
    return {"status": "success", "users": accounts.list_users(query)}


@app.get("/api/admin/overview")
def admin_overview(request: Request):
    accounts.require_admin(request)
    return {"status": "success", "overview": accounts.admin_overview()}


@app.get("/api/admin/users/{user_id}")
def admin_user_detail(user_id: str, request: Request):
    accounts.require_admin(request)
    return {"status": "success", "user": accounts.admin_user_detail(user_id)}


@app.post("/api/admin/impersonate")
def admin_impersonate(payload: ImpersonateRequest, request: Request, response: Response):
    operator = accounts.require_admin(request)
    user = accounts.start_impersonation(operator, payload.user_id, request, response)
    return {"status": "success", "user": user, "wallet": accounts.wallet_summary(user["id"])}


@app.post("/api/auth/stop-impersonation")
def stop_impersonation(request: Request, response: Response):
    user = accounts.stop_impersonation(request, response)
    return {"status": "success", "user": user, "wallet": accounts.wallet_summary(user["id"])}


@app.post("/api/admin/recharge")
def admin_recharge(payload: RechargeRequest, request: Request):
    operator = accounts.require_admin(request)
    wallet = accounts.recharge(operator["id"], payload.user_id, payload.points, payload.bucket, payload.note)
    return {"status": "success", "wallet": wallet}


@app.post("/api/diagnose")
def diagnose(payload: DiagnoseRequest):
    account_name = payload.account_name.strip()
    if not account_name:
        raise HTTPException(status_code=422, detail="请输入公众号名称")
    if not os.getenv("REDFOX_API_KEY"):
        raise HTTPException(status_code=503, detail="服务端尚未配置 REDFOX_API_KEY")

    # The vendored Skill has a CLI-oriented API. The lock keeps its credential
    # and request-scoped output directory isolated during the beta phase.
    with ANALYZER_LOCK:
        previous_output_dir = os.environ.get("WECHAT_ANALYZER_OUTPUT_DIR")
        with tempfile.TemporaryDirectory(prefix="wechat-report-") as request_dir:
            os.environ["WECHAT_ANALYZER_OUTPUT_DIR"] = request_dir
            captured = io.StringIO()
            try:
                with contextlib.redirect_stdout(captured):
                    analyzer.cmd_query(account_names=[account_name])
            except Exception as exc:
                raise HTTPException(status_code=502, detail=f"诊断服务暂时不可用：{exc}") from exc
            finally:
                if previous_output_dir is None:
                    os.environ.pop("WECHAT_ANALYZER_OUTPUT_DIR", None)
                else:
                    os.environ["WECHAT_ANALYZER_OUTPUT_DIR"] = previous_output_dir

            report_path = Path(request_dir) / "report_data.json"
            if report_path.exists():
                report = json.loads(report_path.read_text(encoding="utf-8"))
                raw = report.get("_raw", {}) or {}
                avatar_url = raw.get("avatar") or raw.get("头像") or ""
                if avatar_url.startswith("http://"):
                    avatar_url = "https://" + avatar_url[7:]
                report.setdefault("header", {})["头像链接"] = avatar_url
                report.pop("_raw", None)
                report = _enrich_report(report)
                return {"status": "success", "report": report}

            result = _last_json_line(captured.getvalue()) or {
                "status": "error",
                "message": "未生成诊断报告",
            }
            return JSONResponse(status_code=404 if result.get("query_type") == "not_found" else 502, content=result)


def _image_api_url(base_url: str) -> str:
    base = str(base_url or "https://img.rjm.us.ci").strip().rstrip("/")
    return f"{base if base.endswith('/v1') else base + '/v1'}/images/generations"


def _wait_for_image_task(status_url: str, api_key: str):
    deadline = time.time() + 180
    last_payload = {}
    while time.time() < deadline:
        time.sleep(3)
        try:
            response = requests.get(status_url, headers={"Authorization": f"Bearer {api_key}"}, timeout=35)
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"图片任务查询失败：{exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=f"图片任务返回不是 JSON：{response.text[:300]}") from exc
        last_payload = payload
        if not response.ok:
            raise HTTPException(status_code=response.status_code, detail=payload.get("message") or payload.get("error") or response.text[:300])
        status = str(payload.get("status") or "").lower()
        if status in {"completed", "succeeded", "success"}:
            return payload
        if status in {"failed", "cancelled", "canceled", "error"}:
            error = payload.get("error")
            if isinstance(error, dict):
                error = error.get("message") or error.get("code")
            raise HTTPException(status_code=502, detail=error or payload.get("message") or f"图片任务失败：{status}")
    raise HTTPException(status_code=504, detail=f"图片任务等待超时，最后状态：{last_payload.get('status') or '未知'}")


@app.post("/api/images/generations")
def generate_image(payload: ImageGenerationRequest):
    stored = accounts.provider_settings(include_secrets=True)
    api_key = (stored.get("image_api_key") or os.getenv("WECHAT_IMAGE_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="服务端尚未配置图片 API Key")
    base_url = stored.get("image_base_url") or os.getenv("WECHAT_IMAGE_API_BASE_URL") or os.getenv("WECHAT_API_BASE_URL") or "https://api.openai.com/v1"
    model = stored.get("image_model") or os.getenv("WECHAT_IMAGE_MODEL") or payload.model or "gpt-image-2"
    body = {
        "model": model,
        "prompt": payload.prompt,
        "size": payload.size,
        "n": payload.n,
    }
    try:
        response = requests.post(
            _image_api_url(base_url),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=120,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"图片接口请求失败：{exc}") from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"图片接口返回不是 JSON：{response.text[:300]}") from exc
    if response.status_code == 202 and data.get("statusUrl"):
        return _wait_for_image_task(data["statusUrl"], api_key)
    if not response.ok:
        error = data.get("error")
        if isinstance(error, dict):
            error = error.get("message") or error.get("code")
        raise HTTPException(status_code=response.status_code, detail=error or data.get("message") or response.text[:300])
    if data.get("statusUrl") and not data.get("data"):
        return _wait_for_image_task(data["statusUrl"], api_key)
    return data


@app.get("/api/admin/provider-settings")
def get_provider_settings(request: Request):
    accounts.require_admin(request)
    return {"status": "success", "settings": accounts.provider_settings()}


@app.post("/api/admin/provider-settings")
def save_provider_settings(payload: ProviderSettingsRequest, request: Request):
    admin = accounts.require_admin(request)
    return {"status": "success", "settings": accounts.update_provider_settings(admin["id"], payload.model_dump())}


@app.post("/api/providers/test")
def test_provider(payload: ProviderTestRequest, request: Request):
    accounts.require_admin(request)
    try:
        with workbench.provider_overrides():
            if payload.kind == "text":
                reply = workbench._text("只回复四个字：连接成功")
                return {"status": "success", "kind": "text", "message": reply[:80]}

            api_key = workbench._setting("WECHAT_IMAGE_API_KEY")
            if not api_key:
                raise workbench.ProviderError("尚未填写图片 API Key")
            base = workbench._setting("WECHAT_IMAGE_API_BASE_URL", "https://api.openai.com/v1").rstrip("/")
            models_url = f"{base if base.endswith('/v1') else base + '/v1'}/models"
            session = requests.Session()
            session.trust_env = False
            response = session.get(
                models_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=45,
                verify=workbench._verify_ssl(),
            )
            if not response.ok:
                try:
                    data = response.json()
                except ValueError:
                    data = {}
                error = data.get("error") or {}
                message = error.get("message") if isinstance(error, dict) else str(error)
                raise workbench.ProviderError(f"图片 API HTTP {response.status_code}：{message or '连接验证失败'}")
            return {"status": "success", "kind": "image", "message": "图片服务鉴权成功"}
    except workbench.ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"图片 API 连接失败：{exc}") from exc


@app.post("/api/xiaohongshu/package")
def create_xiaohongshu_package(payload: XiaohongshuRequest):
    try:
        with workbench.provider_overrides():
            package = creator_tools.xiaohongshu_package(
                payload.topic, payload.account, payload.audience,
                payload.goal, payload.evidence, payload.contentType,
            )
            package["precheck"] = creator_tools.xiaohongshu_precheck(
                package.get("selected_title") or payload.topic,
                package.get("body") or "",
            )
            return {"status": "success", "package": package}
    except workbench.ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/tie-tu/plan")
def create_tie_tu_plan(payload: TieTuPlanRequest):
    try:
        with workbench.provider_overrides():
            plan = creator_tools.tie_tu_plan(
                payload.industry, payload.topic, payload.title,
                payload.contentType or None, payload.imageCount,
                payload.style, payload.audience, payload.portraitMode,
            )
            return {"status": "success", "plan": plan}
    except (ValueError, workbench.ProviderError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/creator-tools/image")
def generate_creator_image(payload: CreatorImageRequest):
    try:
        with workbench.provider_overrides():
            result = creator_tools.generate_card_image(
                payload.tool, payload.sessionId, payload.card, payload.style,
            )
            return {"status": "success", "image": result}
    except workbench.ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"图片下载失败：{exc}") from exc


@app.get("/api/creator-tools/assets/{tool}/{session_id}/{filename}")
def get_creator_asset(tool: str, session_id: str, filename: str):
    path = creator_tools.creator_asset(tool, session_id, filename)
    if not path.exists() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)


@app.post("/api/hit-detector/analyze")
def analyze_article(payload: HitDetectorRequest):
    try:
        report = creator_tools.detect_article(
            payload.title, payload.body, payload.track,
            payload.fans, payload.openRate,
        )
        return {"status": "success", "report": report}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"文章复核失败：{exc}") from exc


@app.post("/api/hit-detector/rewrite")
def rewrite_article(payload: HitRewriteRequest):
    try:
        with workbench.provider_overrides():
            rewritten = creator_tools.rewrite_article(
                payload.title, payload.body, payload.detectorResult,
            )
            return {"status": "success", "article": rewritten}
    except workbench.ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _run_workbench_job(job_id: str, user_id: str, session_id: str, payload: dict[str, Any], usage_id: str) -> None:
    started = time.perf_counter()
    accounts.update_workbench_job(job_id, "running")
    try:
        with workbench.provider_overrides():
            workbench.create(
                payload["topic"], payload["mode"], payload["persona"], payload["theme"],
                user_id=user_id, session_id=session_id,
            )
        accounts.settle_usage(usage_id, 200, int((time.perf_counter() - started) * 1000))
        accounts.update_workbench_job(job_id, "completed")
    except Exception as exc:
        accounts.refund_usage(usage_id, 500, int((time.perf_counter() - started) * 1000))
        accounts.update_workbench_job(job_id, "failed", str(exc)[-1000:])


def _public_workbench_job(job: dict[str, Any]) -> dict[str, Any]:
    return {key: job.get(key) for key in (
        "id", "session_id", "status", "error", "created_at", "started_at", "finished_at"
    )}


@app.post("/api/workbench/sessions", status_code=202)
def create_workbench_session(payload: WorkbenchCreateRequest, request: Request):
    user = request.state.user
    with WORKBENCH_JOB_LOCK:
        existing = accounts.workbench_job_by_key(user["id"], payload.idempotency_key)
        if existing:
            return {"status": "accepted", "job": _public_workbench_job(existing), "idempotent_replay": True}
        rule = accounts.pricing_rule("POST", "/api/workbench/sessions")
        if not rule:
            raise HTTPException(status_code=503, detail="公众号完整工作流计费规则未启用")
        usage_id = accounts.reserve_points(user["id"], rule, "POST", "/api/workbench/sessions")
        session_id = uuid.uuid4().hex
        job = accounts.create_workbench_job(
            user["id"], payload.idempotency_key, session_id, usage_id,
        )
        if job.get("usage_id") != usage_id:
            accounts.refund_usage(usage_id, 409, 0)
            return {"status": "accepted", "job": _public_workbench_job(job), "idempotent_replay": True}
        try:
            WORKBENCH_EXECUTOR.submit(
                _run_workbench_job, job["id"], user["id"], session_id,
                {"topic": payload.topic, "mode": payload.mode, "persona": payload.persona, "theme": payload.theme},
                usage_id,
            )
        except Exception as exc:
            accounts.refund_usage(usage_id, 503, 0)
            accounts.update_workbench_job(job["id"], "failed", f"任务调度失败：{exc}")
            raise HTTPException(status_code=503, detail="任务暂时无法调度，积分已退还") from exc
    return {"status": "accepted", "job": _public_workbench_job(job), "idempotent_replay": False}


@app.get("/api/workbench/jobs/{job_id}")
def get_workbench_job(job_id: str, request: Request):
    job = accounts.workbench_job(job_id, request.state.user["id"])
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在或不属于当前用户")
    session = None
    if job["status"] == "completed":
        session = accounts.load_workbench_session(job["session_id"], request.state.user["id"])
        if session:
            session = workbench._session_view(session)
    return {"status": "success", "job": _public_workbench_job(job), "session": session}


@app.get("/api/workbench/provider-status")
def get_workbench_provider_status():
    return {"status": "success", "provider": workbench.provider_status()}


@app.post("/api/workbench/steps")
def advance_workbench(payload: WorkbenchStepRequest, request: Request):
    try:
        with workbench.provider_overrides():
            return {"status": "success", "session": workbench.step(payload.session_id, payload.step, payload.selection, payload.article, user_id=request.state.user["id"])}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except workbench.ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"工作台执行失败：{exc}") from exc


@app.post("/api/workbench/preview")
def preview_workbench(payload: WorkbenchPreviewRequest, request: Request):
    try:
        with workbench.provider_overrides():
            return {"status": "success", "session": workbench.preview(payload.session_id, payload.article, user_id=request.state.user["id"])}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"预览失败：{exc}") from exc


def _require_workbench_owner(session_id: str, request: Request) -> None:
    if not accounts.load_workbench_session(session_id, request.state.user["id"]):
        raise HTTPException(status_code=404, detail="创作会话不存在或不属于当前用户")


@app.get("/api/workbench/preview/{session_id}")
def get_workbench_preview(session_id: str, request: Request):
    _require_workbench_owner(session_id, request)
    path = workbench.preview_file(session_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="预览尚未生成")
    return FileResponse(path, media_type="text/html")


@app.get("/api/workbench/html/{session_id}")
def download_workbench_html(session_id: str, request: Request):
    _require_workbench_owner(session_id, request)
    path = workbench.preview_file(session_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="排版 HTML 尚未生成")
    return FileResponse(path, media_type="text/html", filename=f"wechat-article-{session_id[:8]}.html")


@app.get("/api/workbench/assets/{session_id}/{filename}")
def get_workbench_asset(session_id: str, filename: str, request: Request):
    _require_workbench_owner(session_id, request)
    path = workbench.asset_file(session_id, filename)
    if not path.exists() or path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=404, detail="图片不存在")
    return FileResponse(path)


@app.post("/api/workbench/publish")
def publish_workbench(payload: WorkbenchPublishRequest, request: Request):
    try:
        with workbench.provider_overrides():
            return {"status": "success", "session": workbench.publish(payload.session_id, payload.draft, user_id=request.state.user["id"])}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"发布失败：{exc}") from exc


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
