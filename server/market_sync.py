"""AI 超市：把 GitHub 上的 agent skills 索引同步成一份本地快照。

设计约束（刻意保持简单）：
- 只有一个上游数据源：truefoundry/awesome-skills-registry 的 dist/ai-skills.json
- 不做数据库：快照写到 MARKET_DIR（容器里是已挂载的 /app/output），原子替换
- 人工维护的 custom.json 与快照分离，同步永不覆盖
- 前端不直连 GitHub：所有读取都走本地快照
"""
from __future__ import annotations

import io
import json
import logging
import os
import time
import zipfile
from pathlib import Path
from typing import Any

import requests

from .celery_app import celery_app

logger = logging.getLogger(__name__)

REPO = "truefoundry/awesome-skills-registry"
SOURCES = (
    f"https://raw.githubusercontent.com/{REPO}/main/dist/ai-skills.json",
    f"https://cdn.jsdelivr.net/gh/{REPO}@main/dist/ai-skills.json",
)
ZIP_SOURCE = f"https://codeload.github.com/{REPO}/zip/refs/heads/main"

CATEGORIES = {
    "marketing": "营销",
    "coding": "编程",
    "productivity": "效率",
    "science": "科研",
    "design": "设计",
    "data-ai": "数据与 AI",
    "creative": "创意",
    "business": "商业",
    "legal": "法务",
    "health": "健康",
    "miscellaneous": "其他",
}
MIN_ITEMS = 800
DEFAULT_TRANSLATE_LIMIT = 200


def market_dir() -> Path:
    configured = os.getenv("MARKET_DIR", "").strip()
    path = Path(configured) if configured else Path("/app/output/market")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        # 本地开发 / 单元测试：退回项目内目录
        path = Path(__file__).resolve().parents[1] / "output" / "market"
        path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_path() -> Path:
    return market_dir() / "skills.json"


def meta_path() -> Path:
    return market_dir() / "meta.json"


def custom_path() -> Path:
    return market_dir() / "custom.json"


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    """原子写：先写临时文件，再 os.replace，避免读到半份数据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def github_url(repo: str, path: str) -> str:
    clean = (path or "").strip()
    if clean in {"", "/", "."}:
        return f"https://github.com/{repo}"
    if not clean.startswith("/"):
        clean = "/" + clean
    # HEAD 在 GitHub 的 tree 路由里会解析到默认分支，省掉一次「查 default_branch」的请求
    return f"https://github.com/{repo}/tree/HEAD{clean}"


def _fetch_zip_payload(timeout: int) -> list[dict[str, Any]]:
    response = requests.get(ZIP_SOURCE, timeout=timeout)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        name = next(n for n in archive.namelist() if n.endswith("dist/ai-skills.json"))
        return json.loads(archive.read(name).decode("utf-8"))


def fetch_payload(timeout: int = 25) -> tuple[list[dict[str, Any]], str]:
    errors: list[str] = []
    for url in SOURCES:
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, list) and data:
                return data, url
            errors.append(f"{url}: empty")
        except Exception as exc:  # noqa: BLE001 - 逐级降级
            errors.append(f"{url}: {type(exc).__name__}")
    try:
        data = _fetch_zip_payload(timeout + 15)
        if isinstance(data, list) and data:
            return data, ZIP_SOURCE
        errors.append(f"{ZIP_SOURCE}: empty")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{ZIP_SOURCE}: {type(exc).__name__}")
    raise RuntimeError("所有数据源都不可用: " + "; ".join(errors))


def normalize(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去重（repo+path）、补分类中文名、拼接跳转链接。"""
    merged: dict[str, dict[str, Any]] = {}
    for row in raw:
        if not isinstance(row, dict):
            continue
        source = row.get("source") or {}
        repo = str(source.get("repo") or "").strip()
        path = str(source.get("path") or "").strip()
        title = str(row.get("display_name") or row.get("id") or "").strip()
        if not repo or not title:
            continue
        key = f"{repo}{path}".lower()
        try:
            stars = int((row.get("metadata") or {}).get("stars") or 0)
        except (TypeError, ValueError):
            stars = 0
        category = str(row.get("category") or "miscellaneous").strip()
        item = {
            "id": str(row.get("id") or key),
            "name": title,
            "name_zh": "",
            "description": str(row.get("description") or "").strip(),
            "description_zh": "",
            "category": category,
            "category_zh": CATEGORIES.get(category, "其他"),
            "authors": [str(a) for a in (row.get("authors") or [])][:6],
            "official": bool(row.get("is_official")),
            "tags": [str(t) for t in (row.get("tags") or [])][:12],
            "repo": repo,
            "path": path,
            "url": github_url(repo, path),
            "stars": stars,
            "added_at": str(row.get("added_at") or ""),
            "manual": False,
        }
        current = merged.get(key)
        if current is None or item["stars"] > current["stars"]:
            merged[key] = item
    return sorted(merged.values(), key=lambda item: (-item["stars"], item["name"]))


# ---------------------------------------------------------------- 翻译
def _translate_batch(service, rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    payload = [{"id": row["id"], "name": row["name"], "desc": row["description"][:400]} for row in rows]
    prompt = (
        "把下面的 AI Agent Skill 名称与一句话说明翻译成简体中文。"
        "名称要像产品名一样简洁（不超过 14 个字），说明不超过 42 个字，保留专有名词与产品名。"
        "只返回 JSON 数组，每项字段为 id、name、desc，不要解释。\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    response = service.create_response(
        [{"role": "system", "content": "你是中文技术编辑，只输出合法 JSON。"},
         {"role": "user", "content": prompt}],
        timeout=90, idempotency_key=f"market-translate:{int(time.time())}",
    )
    text = (getattr(response, "text", "") or "").strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return {}
    try:
        rows_out = json.loads(text[start:end + 1])
    except ValueError:
        return {}
    result: dict[str, dict[str, str]] = {}
    for item in rows_out if isinstance(rows_out, list) else []:
        if isinstance(item, dict) and item.get("id"):
            result[str(item["id"])] = {
                "name": str(item.get("name") or "").strip()[:30],
                "desc": str(item.get("desc") or "").strip()[:120],
            }
    return result


def translate(items: list[dict[str, Any]], limit: int = DEFAULT_TRANSLATE_LIMIT) -> int:
    """只翻 star 最高的前 N 条，且只翻还没有中文的；失败不影响落盘。"""
    if os.getenv("MARKET_TRANSLATE", "1").lower() in {"0", "false", "no", "off"}:
        return 0
    pending = [item for item in items[:limit] if not item.get("description_zh")]
    if not pending:
        return 0
    try:
        from .agent.runtime import build_model_service
        service = build_model_service()
    except Exception as exc:  # noqa: BLE001
        logger.warning("market translate skipped: %s", exc)
        return 0
    done = 0
    batch_size = 8
    for index in range(0, len(pending), batch_size):
        batch = pending[index:index + batch_size]
        try:
            translated = _translate_batch(service, batch)
        except Exception as exc:  # noqa: BLE001
            logger.warning("market translate batch failed: %s", exc)
            continue
        for item in batch:
            payload = translated.get(item["id"])
            if not payload:
                continue
            item["name_zh"] = payload["name"]
            item["description_zh"] = payload["desc"]
            done += 1
    return done


# ---------------------------------------------------------------- 同步
def sync(translate_items: bool = True) -> dict[str, Any]:
    started = time.time()
    raw, source = fetch_payload()
    if len(raw) < MIN_ITEMS:
        raise RuntimeError(f"数据不完整（{len(raw)} < {MIN_ITEMS}），已保留上一版")
    items = normalize(raw)
    # 保留上一版已有的人工翻译，避免每次重翻
    previous = {row["id"]: row for row in (read_json(snapshot_path(), {}) or {}).get("items", [])}
    for item in items:
        old = previous.get(item["id"])
        if old and old.get("description_zh"):
            item["name_zh"] = old.get("name_zh", "")
            item["description_zh"] = old.get("description_zh", "")
    translated = translate(items) if translate_items else 0
    payload = {
        "items": items,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": source,
        "count": len(items),
        "translated": sum(1 for item in items if item.get("description_zh")),
    }
    write_json(snapshot_path(), payload)
    write_json(meta_path(), {
        "generated_at": payload["generated_at"], "count": len(items), "source": source,
        "translated": payload["translated"], "newly_translated": translated,
        "duration_ms": int((time.time() - started) * 1000),
        "categories": _category_counts(items),
    })
    logger.info("market sync ok: %s items, %s translated, %sms",
                len(items), payload["translated"], int((time.time() - started) * 1000))
    return {"count": len(items), "translated": payload["translated"], "source": source}


def _category_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return counts


@celery_app.task(name="market.sync", max_retries=2, default_retry_delay=120)
def sync_task():
    try:
        return sync()
    except Exception as exc:  # noqa: BLE001
        logger.warning("market sync failed: %s", exc)
        raise
