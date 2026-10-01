"""Black-box acceptance for the public Native Easel conversation flow.

Creates two uniquely named trial users and consumes one trial task per user.
Does not print passwords, cookies, prompts, or generated content.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import secrets
import time

import requests


def request(session: requests.Session, method: str, url: str, **kwargs) -> dict:
    response = session.request(method, url, timeout=30, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url.rsplit('/', 1)[-1]} returned HTTP {response.status_code}")
    return response.json()


def register(base: str, label: str) -> tuple[requests.Session, str, int]:
    session = requests.Session()
    payload = {
        "email": f"easel-acceptance-{label}-{secrets.token_hex(5)}@example.invalid",
        "password": secrets.token_urlsafe(24),
        "display_name": f"Easel RC {label}",
    }
    result = request(session, "POST", base + "/api/auth/register", json=payload)
    user_id = result["user"]["id"]
    balance = int(result["wallet"]["balance"])
    assert request(session, "GET", base + "/api/auth/me")["user"]["id"] == user_id
    return session, user_id, balance


def submit(base: str, session: requests.Session, skill_id: str, prompt: str) -> tuple[str, str]:
    conversation = request(session, "POST", base + "/api/conversations", json={
        "title": "Easel acceptance", "mode": "manual", "skill_id": skill_id,
    })["conversation"]
    run = request(session, "POST", base + f"/api/conversations/{conversation['id']}/messages",
                  headers={"Idempotency-Key": secrets.token_hex(16)},
                  json={"content": prompt})
    return conversation["id"], run["run_id"]


def await_result(base: str, session: requests.Session, run_id: str, deadline: float) -> dict:
    while time.monotonic() < deadline:
        run = request(session, "GET", base + f"/api/runs/{run_id}")["run"]
        if run["status"] in {"completed", "failed", "cancelled"}:
            return run
        time.sleep(2)
    raise TimeoutError(f"run {run_id} did not finish before deadline")


def events(base: str, session: requests.Session, run_id: str, *, after: int = 0) -> list[dict]:
    with session.get(base + f"/api/runs/{run_id}/events", params={"after": after},
                     headers={"Accept": "text/event-stream"}, stream=True, timeout=45) as response:
        response.raise_for_status()
        assert response.headers["Content-Type"].startswith("text/event-stream")
        rows = []
        for line in response.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                rows.append(json.loads(line[6:]))
        return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    catalog = request(requests.Session(), "GET", base + "/health/ready")
    assert catalog["status"] == "ready"
    a, a_id, a_before = register(base, "a")
    b, b_id, b_before = register(base, "b")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit, base, a, "easel_skill_article_outline",
                            "为中老年人情感需求写一份公众号文章大纲，150字左右。")
        second = pool.submit(submit, base, b, "easel_skill_content_matrix",
                             "为一个面向中老年人的公众号设计三条内容栏目，简要说明定位。")
        a_conversation, a_run = first.result(timeout=30)
        b_conversation, b_run = second.result(timeout=30)
    deadline = time.monotonic() + 240
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(await_result, base, a, a_run, deadline)
        second = pool.submit(await_result, base, b, b_run, deadline)
        a_result = first.result(timeout=250)
        b_result = second.result(timeout=250)
    assert a_result["status"] == b_result["status"] == "completed", (a_result["status"], b_result["status"])
    for label, session, other, uid, cid, run_id, before in (
        ("a", a, b, a_id, a_conversation, a_run, a_before),
        ("b", b, a, b_id, b_conversation, b_run, b_before),
    ):
        rows = events(base, session, run_id)
        assert any(item["type"] == "run.completed" for item in rows)
        assert rows == sorted(rows, key=lambda item: item["id"])
        assert events(base, session, run_id, after=rows[-2]["id"])[-1]["id"] == rows[-1]["id"]
        artifacts = request(session, "GET", base + f"/api/conversations/{cid}/artifacts")["artifacts"]
        assert artifacts and len(artifacts[-1].get("content") or "") >= 40
        assert request(session, "GET", base + f"/api/conversations/{cid}")["conversation"]["user_id"] == uid
        after = int(request(session, "GET", base + "/api/wallet")["wallet"]["balance"])
        assert before - after == 10, (label, before, after)
        assert other.get(base + f"/api/runs/{run_id}", timeout=20).status_code == 404
        assert other.get(base + f"/api/conversations/{cid}/artifacts", timeout=20).status_code == 404
        assert other.get(base + f"/api/runs/{run_id}/events", timeout=20).status_code == 404
        print(f"user_{label}: completed; events={len(rows)}; artifacts={len(artifacts)}; points={before}->{after}; isolation=pass")
    print("EASEL_NATIVE_HTTP_ACCEPTANCE=PASS")


if __name__ == "__main__":
    main()
