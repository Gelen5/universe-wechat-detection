"""Fail fast when a configured node model is not available.

Relay stations rename models and change what a subscription group may call, so
a model that worked last week can return ``model_not_found`` for this account
today. Without this probe the first symptom is a user's node failing mid-run
after the points were reserved.

Run it inside the web/worker container (it reads the app's own settings):

    python scripts/check_node_models.py

Exit code 0 when every configured model answers, 1 otherwise.
"""
from __future__ import annotations

import os
import sys
from typing import Any

import requests

from server import accounts

# Every knob the pipeline can send a model name to.
NODE_VARS = (
    "WECHAT_TEXT_MODEL",
    "WECHAT_INTENT_MODEL",
    "WECHAT_TOPIC_MODEL",
    "WECHAT_OUTLINE_MODEL",
    "WECHAT_DRAFT_MODEL",
    "WECHAT_REVIEW_MODEL",
    "WECHAT_LAYOUT_MODEL",
)
DEFAULT_MODEL = "gpt-4.1-mini"
PROBE_TIMEOUT = 45


def _chat_root(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/responses"):
        base = base[: -len("/responses")]
    return base.rstrip("/")


def effective_models(stored: dict[str, Any]) -> dict[str, list[str]]:
    """Map each configured model name to the settings that use it."""
    # ``provider_settings.text_model`` outranks the environment for the text
    # model, exactly like ``workbench._setting`` does at request time.
    text_model = str(stored.get("text_model") or "").strip() or \
        os.getenv("WECHAT_TEXT_MODEL", "").strip() or DEFAULT_MODEL
    used: dict[str, list[str]] = {}
    for name in NODE_VARS:
        if name == "WECHAT_TEXT_MODEL":
            model = text_model
        else:
            model = os.getenv(name, "").strip() or text_model
        used.setdefault(model, []).append(name.replace("WECHAT_", "").replace("_MODEL", "").lower())
    return used


def probe(url: str, key: str, model: str) -> tuple[bool, str]:
    try:
        response = requests.post(
            url,
            timeout=PROBE_TIMEOUT,
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "max_tokens": 1,
                  "messages": [{"role": "user", "content": "hi"}]},
        )
    except Exception as exc:  # network/relay failure is not a model verdict
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"
    if response.status_code == 200:
        return True, "ok"
    detail = (response.text or "").replace("\n", " ").strip()
    return False, f"{response.status_code} {detail[:140]}"


def main() -> int:
    stored = accounts.provider_settings(include_secrets=True)
    key = str(stored.get("text_api_key") or "").strip()
    base = str(stored.get("text_base_url") or "").strip() or \
        os.getenv("WECHAT_TEXT_API_BASE_URL", "").strip() or \
        os.getenv("WECHAT_API_BASE_URL", "").strip()
    url = _chat_root(base) + "/chat/completions"
    if not key or not base:
        print("  未配置文字 API，跳过模型检查")
        return 0

    results = []
    for model, settings in sorted(effective_models(stored).items()):
        ok, detail = probe(url, key, model)
        results.append((model, settings, ok, detail))
        mark = "ok  " if ok else "FAIL"
        print(f"  {mark} {model:<20} {','.join(settings)}" + ("" if ok else f"  <- {detail}"))

    failed = [row for row in results if not row[2]]
    if failed:
        print(f"  有 {len(failed)} 个模型不可用：{', '.join(row[0] for row in failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
