"""Public black-box acceptance for WeChat topic evidence; consumes trial points."""
from __future__ import annotations

import argparse
import secrets
import time

import requests
from bs4 import BeautifulSoup


def assert_body_image_position(html: str) -> None:
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("#article-content") or soup
    nodes = [node for node in article.find_all(["p", "img"])
             if node.name == "img" or (len(node.get_text(strip=True)) >= 10
                                      and not node.get_text(strip=True).startswith("图注："))]
    image_positions = [index for index, node in enumerate(nodes)
                       if node.name == "img" and str(node.get("src", "")).startswith("data:image/")]
    assert image_positions, "final HTML omitted generated image"
    assert any(any(node.name == "p" for node in nodes[:index])
               and any(node.name == "p" for node in nodes[index + 1:])
               for index in image_positions), "generated body image was not placed between article paragraphs"


def call(session: requests.Session, method: str, url: str, **kwargs):
    response = session.request(method, url, timeout=30, **kwargs)
    response.raise_for_status()
    return response.json()


def wait_run(session: requests.Session, base: str, run_id: str, seconds: int) -> dict:
    deadline = time.monotonic() + seconds
    next_report = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            run = call(session, "GET", base + f"/api/runs/{run_id}")["run"]
        except requests.RequestException:
            time.sleep(2)
            continue
        if run["status"] in {"completed", "failed", "cancelled", "waiting_input"}:
            return run
        if time.monotonic() >= next_report:
            print(f"WECHAT_RUN_STATUS={run['status']} run={run_id}", flush=True)
            next_report = time.monotonic() + 30
        time.sleep(2)
    raise TimeoutError(f"WeChat run {run_id} did not finish")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url")
    parser.add_argument("--with-article", action="store_true")
    parser.add_argument("--with-layout", action="store_true")
    parser.add_argument("--image-only", action="store_true")
    parser.add_argument("--image-layout-only", action="store_true")
    parser.add_argument("--review-only", action="store_true")
    parser.add_argument("--with-image-layout", action="store_true")
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
    if args.review_only:
        article = ("周日下午，父亲把手机递过来，让我帮他把常去的医院存进地图。"
                   "我点开收藏夹，发现里面只有家和菜市场。他说以前没觉得要记这些地方。\n\n"
                   "我们坐在餐桌旁，一起核对医院入口、公交站和回程路线。"
                   "他记在纸上，我在手机里做了标记。快出门时，他又问了一遍站名。\n\n"
                   "那天我才发现，教会一个操作并不等于对方从此不会遇到困难。"
                   "下次回家，我想先问问他还有哪里走得不踏实。")
        run_id = call(session, "POST", base + f"/api/conversations/{cid}/messages",
                      headers={"Idempotency-Key": secrets.token_hex(16)}, json={
                          "content": "请直接调用 review_article 审阅下面这篇已写好的文章；"
                                     "必须运行复核 Skill，并保存修订文章与复核报告，不要写新文章。\n\n" + article,
                      })["run_id"]
        run = wait_run(session, base, run_id, 600)
        assert run["status"] == "completed", run["status"]
        artifacts = call(session, "GET", base + f"/api/conversations/{cid}/artifacts")["artifacts"]
        reports = [item for item in artifacts if item["type"] == "report"]
        assert reports and (reports[-1].get("content_json") or {}).get("gate") == "passed"
        after = int(call(session, "GET", base + "/api/wallet")["wallet"]["balance"])
        assert before - after == 10, (before, after)
        print(f"WECHAT_REVIEW_ACCEPTANCE=PASS report={reports[-1]['id']} points={before}->{after}")
        return
    if args.with_image_layout:
        for prompt, expected_type, seconds in (
            ("请写一篇约500字、关于中老年人如何与成年子女保持边界的完整公众号文章，调用写作工具保存正文。", "article", 1800),
            ("请为刚才的文章调用 generate_image 生成一张清晨家庭客厅的正文配图，保存图片作品。", "image", 1800),
            ("请先审稿，再把刚才的文章与已生成配图一起排成公众号 HTML，图片必须出现在文章中。", "html", 1800),
        ):
            run_id = call(session, "POST", base + f"/api/conversations/{cid}/messages",
                          headers={"Idempotency-Key": secrets.token_hex(16)},
                          json={"content": prompt})["run_id"]
            run = wait_run(session, base, run_id, seconds)
            assert run["status"] == "completed", (expected_type, run["status"])
            artifacts = call(session, "GET", base + f"/api/conversations/{cid}/artifacts")["artifacts"]
            current = [item for item in artifacts if item["type"] == expected_type]
            assert current, f"{expected_type} artifact missing"
            print(f"WECHAT_IMAGE_LAYOUT_STEP={expected_type} PASS", flush=True)
        assert_body_image_position(current[-1].get("content") or "")
        after = int(call(session, "GET", base + "/api/wallet")["wallet"]["balance"])
        assert before - after == 30, (before, after)
        print(f"WECHAT_IMAGE_LAYOUT_ACCEPTANCE=PASS html_chars={len(current[-1]['content'])} "
              f"points={before}->{after}")
        return
    if args.image_only or args.image_layout_only:
        run_id = call(session, "POST", base + f"/api/conversations/{cid}/messages",
                      headers={"Idempotency-Key": secrets.token_hex(16)}, json={
                          "content": "请调用 generate_image 工具生成一张清晨窗边的公众号文章配图，保存图片作品。不要只用文字描述。",
                      })["run_id"]
        run = wait_run(session, base, run_id, 360)
        assert run["status"] == "completed", run["status"]
        artifacts = call(session, "GET", base + f"/api/conversations/{cid}/artifacts")["artifacts"]
        images = [item for item in artifacts if item["type"] == "image"]
        assert images, "generate_image did not persist an image artifact"
        after = int(call(session, "GET", base + "/api/wallet")["wallet"]["balance"])
        assert before - after == 10, (before, after)
        print(f"WECHAT_IMAGE_ACCEPTANCE=PASS images={len(images)} points={before}->{after}")
        if args.image_layout_only:
            article = ("# 一顿饭的距离\n\n周末回家，母亲刚把汤端上桌，就问起下个月的安排。"
                       "我原想说还没想好，却发现她已经把日历翻到了那一页。\n\n"
                       "饭后我们一起收拾碗筷。我说，等工作安排确定后再告诉你。"
                       "她点点头，没有继续追问。厨房里的水声比刚才的谈话更轻。\n\n"
                       "亲近不必等于随时汇报。能把话说清楚，也能给彼此留一点时间，下一次见面才不必从解释开始。")
            run_id = call(session, "POST", base + f"/api/conversations/{cid}/messages",
                          headers={"Idempotency-Key": secrets.token_hex(16)}, json={
                              "content": "请直接调用 typeset_article，将下面这篇已写好的文章排成公众号 HTML；"
                                         "使用当前对话刚才生成的图片，不要重写正文或重新生成图片。\n\n" + article,
                          })["run_id"]
            run = wait_run(session, base, run_id, 360)
            assert run["status"] == "completed", run["status"]
            artifacts = call(session, "GET", base + f"/api/conversations/{cid}/artifacts")["artifacts"]
            html = [item for item in artifacts if item["type"] == "html"]
            assert html, "HTML artifact missing"
            assert_body_image_position(html[-1].get("content") or "")
            final_balance = int(call(session, "GET", base + "/api/wallet")["wallet"]["balance"])
            assert after - final_balance == 10, (after, final_balance)
            print(f"WECHAT_IMAGE_LAYOUT_ONLY=PASS html_chars={len(html[-1]['content'])} "
                  f"points={after}->{final_balance}")
        return
    run_id = call(session, "POST", base + f"/api/conversations/{cid}/messages",
                  headers={"Idempotency-Key": secrets.token_hex(16)}, json={
                      "content": "请查询最近一周中老年情感相关热点，给我3个有来源和日期的公众号选题；不能核实的标为创意建议。",
                  })["run_id"]
    run = wait_run(session, base, run_id, 240)
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
        run = wait_run(session, base, run_id, 300)
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
            run = wait_run(session, base, run_id, 420)
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
