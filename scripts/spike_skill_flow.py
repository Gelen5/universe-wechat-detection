"""Spike: drive the installed weChat-autoCreate ArticleState workflow as a host.

Usage (inside the web container, where the Skill is mounted):

    python scripts/spike_skill_flow.py --request "写一篇给职场人的 AI 工具实测"

It runs the Skill's own 7-node machine up to the requested node, prints a
timeline, and (with --compare) also runs the current workbench 选题 for the
same request so the two can be compared side by side. Nothing touches the
production tables; state and outputs go under /app/output/spike.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.agent.runtime import build_model_service  # noqa: E402
from server.article_host import ArticleHost, WorkflowBlocked  # noqa: E402

SKILL_DIR = Path(os.getenv("WECHAT_PUBLISHER_SKILL_DIR")
                 or "/opt/universe-skills/weChat-autoCreate")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--stop-after", default="topic")
    parser.add_argument("--compare", action="store_true")
    parser.add_argument("--timely", action="store_true")
    args = parser.parse_args()

    run_id = uuid.uuid4().hex[:10]
    root = Path("/app/output/spike") / run_id
    host = ArticleHost(
        skill_dir=SKILL_DIR, state_path=root / "state.json",
        output_dir=root, model_service=build_model_service(),
    )
    print(f"skill: {SKILL_DIR}")
    print(f"state: {root / 'state.json'}")

    def on_event(kind, note):
        print(f"  [{kind}] {note.get('label')} (node={note.get('node')}) "
              f"t={note.get('at')}s" + (f" +{note.get('seconds')}s" if note.get("seconds") else ""))

    started = time.time()
    host.init(args.request, mode="interactive", timely=args.timely)
    try:
        result = host.drive(stop_after=args.stop_after, on_event=on_event)
    except WorkflowBlocked as exc:
        print(f"BLOCKED after {time.time()-started:.1f}s: {exc}")
        return 3
    print(f"status={result['status']} total={result['seconds']}s")
    print("nodes:", json.dumps({k: v["status"] for k, v in result["state"]["nodes"].items()},
                               ensure_ascii=False))

    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    for key in ("topic", "angle", "audience", "selected_title"):
        if state.get(key):
            print(f"{key}: {state[key]}")
    for key in ("intent", "title_candidates"):
        if state.get(key):
            print(f"{key}: {json.dumps(state[key], ensure_ascii=False)[:800]}")

    if args.compare:
        from server import workbench
        print("\n--- 现状：workbench._suggestions 对照 ---")
        began = time.time()
        session = {}
        from server.skills.adapter_support import with_provider
        topics = with_provider(lambda: workbench._suggestions(args.request, "深度观察者", session))
        print(f"elapsed={time.time()-began:.1f}s topics={len(topics)}")
        for item in topics[:5]:
            print(f"  - {item['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
