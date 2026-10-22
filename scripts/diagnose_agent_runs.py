#!/usr/bin/env python3
"""排查公众号创作（conversation Run）失败原因。

线上那条 "本轮执行失败，已按规则退还积分" 来自前端 failureText() 的兜底文案：
`_run_view()` 只把 error_code 映射成 4 种 error_kind，其余一律通用文案，
真正的 error_code / error_message 只落在 runs 表、run_events、tool_calls 里。
这个脚本就是去把这几个表里的真话读出来。

用法（在部署机、项目根目录、已激活应用环境里执行）：

    # 最近 10 条失败/取消的 run，带阶段、错误、工具调用
    python scripts/diagnose_agent_runs.py

    # 只看某个对话（前端 localStorage 里的 conversation id）
    python scripts/diagnose_agent_runs.py --conversation 8f3c... --limit 20

    # 看全部状态，定位"卡在 queued / running"的僵尸 run
    python scripts/diagnose_agent_runs.py --all --limit 30

    # 精确看一条 run 的完整时间线
    python scripts/diagnose_agent_runs.py --run 4a1b...

只读，不写库。DATABASE_URL 从环境变量读（和 web/worker 用同一个）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from server.database import ENGINE  # noqa: E402

STAGE_LABEL = {
    "topic": "选题", "outline": "大纲", "writing": "写作",
    "deai": "去 AI", "typeset": "排版", None: "（未标阶段/自由对话）",
}

RUN_SQL = """
SELECT id, conversation_id, trigger_message_id, skill_id, status, attempt,
       error_code, error_message, celery_task_id, cost_points,
       created_at, started_at, finished_at, heartbeat_at
FROM runs
{where}
ORDER BY created_at DESC
LIMIT :limit
"""


def rows(sql: str, **params):
    with ENGINE.connect() as connection:
        return [dict(row._mapping) for row in connection.execute(text(sql), params)]


def one(sql: str, **params):
    with ENGINE.connect() as connection:
        row = connection.execute(text(sql), params).first()
        return dict(row._mapping) if row else None


def trigger(message_id: str | None) -> dict:
    if not message_id:
        return {}
    return one("SELECT content, content_json, role, created_at FROM messages WHERE id = :id",
               id=message_id) or {}


def tool_calls(run_id: str) -> list[dict]:
    return rows(
        "SELECT tool_name, status, error_message, "
        "       substr(arguments_json, 1, 220) AS arguments, created_at "
        "FROM tool_calls WHERE run_id = :run_id ORDER BY created_at", run_id=run_id)


def events(run_id: str) -> list[dict]:
    return rows(
        "SELECT event_type, payload_json, created_at FROM run_events "
        "WHERE run_id = :run_id ORDER BY id", run_id=run_id)


def clip(value, size: int = 400) -> str:
    text_value = "" if value is None else str(value)
    text_value = text_value.replace("\n", " ")
    return text_value if len(text_value) <= size else text_value[:size] + " …"


def print_run(run: dict, *, detailed: bool) -> None:
    message = trigger(run.get("trigger_message_id"))
    content_json = message.get("content_json") or {}
    if isinstance(content_json, str):
        try:
            content_json = json.loads(content_json)
        except ValueError:
            content_json = {}
    stage = content_json.get("workflow_stage")
    print("=" * 78)
    print(f"run     {run['id']}")
    print(f"对话    {run['conversation_id']}   skill={run.get('skill_id')}   "
          f"状态={run['status']}   attempt={run.get('attempt')}")
    print(f"阶段    {STAGE_LABEL.get(stage, stage)}    "
          f"积分={run.get('cost_points')}    任务={run.get('celery_task_id')}")
    print(f"时间    created={run.get('created_at')} started={run.get('started_at')} "
          f"finished={run.get('finished_at')} heartbeat={run.get('heartbeat_at')}")
    print(f"错误码  {run.get('error_code')}")
    print(f"错误    {clip(run.get('error_message'), 900)}")
    print(f"用户    {clip(message.get('content'), 500)}")

    calls = tool_calls(run["id"])
    if calls:
        print("工具    " + ", ".join(
            f"{item['tool_name']}[{item['status']}]" for item in calls))
        for item in calls:
            if item["status"] != "completed" or item.get("error_message"):
                print(f"   ! {item['tool_name']} 参数={clip(item.get('arguments'), 200)}")
                print(f"     {clip(item.get('error_message'), 600)}")

    if detailed:
        for event in events(run["id"]):
            print(f"   · {event['created_at']} {event['event_type']} "
                  f"{clip(event.get('payload_json'), 300)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="排查公众号创作 Run 的失败原因")
    parser.add_argument("--conversation", help="只看这个对话")
    parser.add_argument("--run", help="只看这一条 run（并打印完整事件流）")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--all", action="store_true", help="包含成功/进行中的 run")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而不是文本")
    args = parser.parse_args()

    if os.getenv("DATABASE_URL"):
        print(f"# DB {os.getenv('DATABASE_URL').split('@')[-1]}", file=sys.stderr)
    else:
        print("# DATABASE_URL 未设置，回退到本地 sqlite（部署机通常不是这个）", file=sys.stderr)

    if args.run:
        found = rows("SELECT * FROM runs WHERE id = :id", id=args.run)
        if not found:
            print("没有找到这条 run", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"run": found[0], "events": events(args.run)}, ensure_ascii=False, indent=2))
            return 0
        print_run(found[0], detailed=True)
        return 0

    where, params = [], {"limit": max(1, min(args.limit, 200))}
    if args.conversation:
        where.append("conversation_id = :conversation_id")
        params["conversation_id"] = args.conversation
    if not args.all:
        where.append("status IN ('failed', 'cancelled', 'queued', 'running')")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    found = rows(RUN_SQL.format(where=clause), **params)

    if not found:
        print("没有匹配的 run。试试 --all。")
        return 0

    summary: dict[str, int] = {}
    for run in found:
        key = f"{run['status']} / {run.get('error_code') or '-'}"
        summary[key] = summary.get(key, 0) + 1

    if args.json:
        payload = [{**run, "trigger": trigger(run.get("trigger_message_id")),
                    "tools": tool_calls(run["id"])} for run in found]
        print(json.dumps({"summary": summary, "runs": payload}, ensure_ascii=False, indent=2, default=str))
        return 0

    print("# 汇总")
    for key, count in sorted(summary.items(), key=lambda item: -item[1]):
        print(f"  {count:3d}  {key}")
    print()
    for run in found:
        print_run(run, detailed=False)

    print()
    print("# 下一步")
    print("  阶段=选题 且 错误里有 '热点抓取' → 服务器出不了网或被 60s 超时卡住（skill_runtime.script）")
    print("  错误里有 'Skill 未完整安装'      → WECHAT_PUBLISHER_SKILL_DIR / 只读挂载不全")
    print("  错误里有 '连续两次未返回合法 JSON' → 选题要求 10 条 JSON 太紧，模型截断")
    print("  错误里有 '选题不足10个' / '去重后' → 同一道硬门槛")
    print("  error_code=http_error/transport   → 文本 API 额度、白名单或网络")
    print("  状态卡在 queued 且无 celery_task  → worker 没消费 chat 队列")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
