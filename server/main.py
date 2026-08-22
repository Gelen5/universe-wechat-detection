import contextlib
import io
import json
import os
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import wechat_analyzer as analyzer


ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"
ANALYZER_LOCK = threading.RLock()

app = FastAPI(
    title="公众号账号诊断",
    description="公众号数据诊断与可视化报告",
    version="0.1.0",
)


class DiagnoseRequest(BaseModel):
    account_name: str = Field(min_length=1, max_length=80)


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
    avg_read = _num(header.get("平均阅读数"))
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

    if overall < 45:
        verdict = "账号还在冷启动阶段，当前最重要的不是继续包装，而是连续发布并拿到第一批真实反馈。"
    elif overall < 65:
        verdict = "账号已经有基本方向，但内容稳定性和用户反馈还没有形成可重复的增长信号。"
    else:
        verdict = "账号已经具备一定运营基础，下一步应围绕高表现主题做系列化放大。"

    recommendations = [
        {
            "priority": "紧急",
            "title": "先建立 10 篇有效样本",
            "evidence": f"近期开文 {len(works)} 篇，平均阅读 {int(avg_read)}，当前样本不足以判断长期表现。",
            "action": "固定一个主栏目和一个发布时间，连续发布 10 篇同一场景内容，再比较阅读和互动变化。",
            "target": "目标：形成可比较的数据基线，而不是追求单篇爆款。",
        },
        {
            "priority": "紧急",
            "title": "把互动问题写进正文结尾",
            "evidence": f"当前互动率 {interaction_rate:.1f}%，点赞 {int(likes)}、评论 {int(comments)}、在看 {int(watch)}。",
            "action": "每篇只保留一个具体问题，例如“你会把这句话发给谁？”并给出可直接转发的短句。",
            "target": "目标：先让互动率达到 1%，再继续优化内容表达。",
        },
        {
            "priority": "重点",
            "title": "把情绪定位变成使用场景",
            "evidence": "账号名称和简介有情绪辨识度，但用户还不清楚关注后能持续获得什么。",
            "action": "从睡前情感陪伴、情侣沟通、关系修复中选一个主场景，连续做成栏目。",
            "target": "目标：让用户在 3 秒内知道这个账号为什么值得关注。",
        },
        {
            "priority": "重点",
            "title": "标题从表达情绪改成命中处境",
            "evidence": "当前作品标题偏情绪表达，缺少明确的关系冲突和读者代入入口。",
            "action": "使用“具体对象 + 关系场景 + 情绪结果”的标题结构，减少泛泛的抒情句。",
            "target": "目标：提高点击意愿，并为后续复盘留下可比较的标题变量。",
        },
        {
            "priority": "持续",
            "title": "建立每周复盘卡片",
            "evidence": "当前账号数据样本少，暂时不能把偶然表现当成稳定规律。",
            "action": "每周记录阅读、点赞、评论、在看和发布时间，只保留表现最好的 2 个主题继续迭代。",
            "target": "目标：20 篇后再做一次方向判断，避免凭感觉换定位。",
        },
    ]

    report["web_insights"] = {
        "verdict": verdict,
        "sample_size": len(works),
        "avg_read": int(avg_read),
        "total_reads": int(total_reads),
        "likes": int(likes),
        "comments": int(comments),
        "watch": int(watch),
        "interaction_rate": round(interaction_rate, 1),
        "last_publish": last_publish or "暂无",
        "dimensions": dimensions,
        "recommendations": recommendations,
        "confidence": "低" if len(works) < 5 else ("中" if len(works) < 10 else "高"),
    }
    return report


@app.get("/health")
def health():
    return {"status": "ok", "service": "wechat-account-detection"}


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


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
