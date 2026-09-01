"""Worker-safe adapter for the bundled WeChat account analyzer."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
from pathlib import Path
from typing import Callable

from . import wechat_analyzer as analyzer


class DiagnosisError(RuntimeError):
    """A user-visible diagnosis failure that is safe to store with a job."""


def run(account_name: str, enrich: Callable[[dict], dict]) -> dict:
    """Create one report in an explicit per-task directory; never mutate os.environ."""
    name = account_name.strip()
    if not name:
        raise DiagnosisError("请输入公众号名称")
    captured = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="wechat-report-") as output_dir:
        try:
            with analyzer.output_dir_override(output_dir), contextlib.redirect_stdout(captured):
                analyzer.cmd_query(account_names=[name])
        except Exception as exc:
            raise DiagnosisError(f"诊断服务暂时不可用：{exc}") from exc
        report_path = Path(output_dir) / "report_data.json"
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            raw = report.get("_raw", {}) or {}
            avatar_url = raw.get("avatar") or raw.get("头像") or ""
            if avatar_url.startswith("http://"):
                avatar_url = "https://" + avatar_url[7:]
            report.setdefault("header", {})["头像链接"] = avatar_url
            report.pop("_raw", None)
            return {"status": "success", "report": enrich(report)}
        result = _last_json_line(captured.getvalue()) or {
            "status": "error", "message": "未生成诊断报告",
        }
        raise DiagnosisError(result.get("message") or "诊断未返回有效报告")


def _last_json_line(output: str) -> dict | None:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None
