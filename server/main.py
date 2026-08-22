import contextlib
import io
import json
import os
import tempfile
import threading
from datetime import datetime
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


def _work_text(work):
    return str(work.get("标题") or work.get("title") or "").strip()


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
    description = str(header.get("账号简介") or "").strip()
    titles = [_work_text(work) for work in works if _work_text(work)]
    title_lengths = [len(title) for title in titles]
    avg_title_length = sum(title_lengths) / len(title_lengths) if title_lengths else 0
    latest = _time_value(works[0].get("发布时间")) if works else None
    oldest = _time_value(works[-1].get("发布时间")) if works else None
    span_days = (latest - oldest).days if latest and oldest else 0
    top_title = titles[0] if titles else "暂无有效标题"
    weakest = min(dimensions, key=lambda item: item["score"]) if dimensions else {"name": "数据", "score": 0}
    weakest_name = weakest["name"]
    sample = len(works)

    if not works:
        verdict = f"{name}目前没有足够的作品数据，暂时不能判断内容方向和运营效果。"
    elif weakest_name == "用户活跃度":
        verdict = f"{name}已有 {sample} 篇可分析作品，但互动反馈偏弱，当前应先围绕高阅读内容设计可回应的问题。"
    elif weakest_name == "内容核心数据表现":
        verdict = f"{name}的内容样本已经形成，但平均阅读约 {int(avg_read)}，目前瓶颈在曝光和单篇表现。"
    elif weakest_name == "内容健康度":
        verdict = f"{name}近期内容有发布样本，但主题和表达还不够稳定，先从数据里表现较好的主题做连续栏目。"
    elif weakest_name == "运营规范性":
        verdict = f"{name}的内容基础尚可，主要问题是更新节奏或账号基础信号不稳定，需要先建立可持续的发布周期。"
    else:
        verdict = f"{name}当前综合表现为 {float(scores.get('综合评分') or 0):.1f} 分，下一步应围绕最低分的{weakest_name}持续验证。"

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
    return routes[:5], verdict


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

    recommendations, verdict = _dynamic_recommendations(
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
