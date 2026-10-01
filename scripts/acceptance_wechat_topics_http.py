"""Public black-box acceptance for WeChat topic evidence; consumes trial points."""
from __future__ import annotations

import argparse
import secrets
import time

import requests


def call(session: requests.Session, method: str, url: str, **kwargs):
    response = session.request(method, url, timeout=30, **kwargs)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--with-article", action="store_true")
    parser.add_argument("--with-layout", action="store_true")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    session = requests.Session()
    account = call(session, "POST", base + "/api/auth/register", json={
        "email": f"wechat-topics-acceptance-{secrets.token_hex(6)}@example.invalid",
        "password": secrets.token_urlsafe(24), "display_name": "Topic Acceptance",
    })
    before = int(account["wallet"]["balance"])
    conversation = call(session, "POST", base + "/api/conversations", json={
        "title": "公众号选题验收", "mode": "manual", "skill_id": "wechat_writer",
    })["conversation"]
    cid = conversation["id"]
    run_id = call(session, "POST", base + f"/api/conversations/{cid}/messages",
                  headers={"Idempotency-Key": secrets.token_hex(16)}, json={
                      "content": "请查询最近一周中老年情感相关热点，给我3个有来源和日期的公众号选题；不能核实的标为创意建议。",
                  })["run_id"]
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        run = call(session, "GET", base + f"/api/runs/{run_id}")["run"]
        if run["status"] in {"completed", "failed", "cancelled", "waiting_input"}:
            break
        time.sleep(2)
    else:
        raise TimeoutError("WeChat topic run did not finish")
    assert run["status"] == "completed", run["status"]
    artifacts = call(session, "GET", base + f"/api/conversations/{cid}/artifacts")["artifacts"]
    topics = [item for item in artifacts if item["type"] == "topic"]
    assert topics, "search_topics did not persist a topic artifact"
    item = topics[-1]
    evidence = (item.get("content_json") or {}).get("evidence") or {}
    assert "checked_at" in evidence and "search_sources" in evidence and "platform_hotspots" in evidence
    assert "模型拟定的方向" in item["content"]
    if not evidence["search_sources"]:
        assert "未获取到可引用的近期搜索来源" in item["content"]
    else:
        assert all(source["url"].startswith("https://") for source in evidence["search_sources"])
    after = int(call(session, "GET", base + "/api/wallet")["wallet"]["balance"])
    assert before - after == 10, (before, after)
    print(f"WECHAT_TOPICS_ACCEPTANCE=PASS sources={len(evidence['search_sources'])} "
          f"platform_hotspots={len(evidence['platform_hotspots'])} points={before}->{after}")
    if args.with_article or args.with_layout:
        run_id = call(session, "POST", base + f"/api/conversations/{cid}/messages",
                      headers={"Idempotency-Key": secrets.token_hex(16)}, json={
                          "content": "采用刚才的第1个方向，写一篇约500字的完整公众号文章。请调用写作工具并保存文章作品。",
                      })["run_id"]
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            run = call(session, "GET", base + f"/api/runs/{run_id}")["run"]
            if run["status"] in {"completed", "failed", "cancelled", "waiting_input"}:
                break
            time.sleep(2)
        else:
            raise TimeoutError("WeChat article run did not finish")
        assert run["status"] == "completed", run["status"]
        artifacts = call(session, "GET", base + f"/api/conversations/{cid}/artifacts")["artifacts"]
        articles = [entry for entry in artifacts if entry["type"] == "article"]
        assert articles and len(articles[-1].get("content") or "") >= 300, "write_article did not save a full article"
        final_balance = int(call(session, "GET", base + "/api/wallet")["wallet"]["balance"])
        assert after - final_balance == 10, (after, final_balance)
        print(f"WECHAT_ARTICLE_ACCEPTANCE=PASS chars={len(articles[-1]['content'])} "
              f"points={after}->{final_balance}")
        if args.with_layout:
            run_id = call(session, "POST", base + f"/api/conversations/{cid}/messages",
                          headers={"Idempotency-Key": secrets.token_hex(16)}, json={
                              "content": "请先调用 review_article 复核刚才保存的完整文章，再调用 typeset_article 用极简白主题排版，保存可下载的公众号 HTML。不得只口头说已完成。",
                          })["run_id"]
            deadline = time.monotonic() + 420
            while time.monotonic() < deadline:
                run = call(session, "GET", base + f"/api/runs/{run_id}")["run"]
                if run["status"] in {"completed", "failed", "cancelled", "waiting_input"}:
                    break
                time.sleep(2)
            else:
                raise TimeoutError("WeChat layout run did not finish")
            assert run["status"] == "completed", run["status"]
            artifacts = call(session, "GET", base + f"/api/conversations/{cid}/artifacts")["artifacts"]
            html = [entry for entry in artifacts if entry["type"] == "html"]
            assert html and "<" in (html[-1].get("content") or ""), "typeset_article did not persist HTML"
            after_layout = int(call(session, "GET", base + "/api/wallet")["wallet"]["balance"])
            assert final_balance - after_layout == 10, (final_balance, after_layout)
            print(f"WECHAT_LAYOUT_ACCEPTANCE=PASS html_chars={len(html[-1]['content'])} "
                  f"points={final_balance}->{after_layout}")


if __name__ == "__main__":
    main()
