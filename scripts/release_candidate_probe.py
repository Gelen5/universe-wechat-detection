"""Black-box release-candidate workflow and restart acceptance probe."""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests


TERMINAL = {"completed", "failed", "cancelled"}


class SSEProbe:
    def __init__(self, base: str, workflow_id: str, cookies: dict[str, str]):
        self.url = f"{base}/api/workflows/{workflow_id}/events"
        self.cookies = cookies
        self.last_id = 0
        self.types: list[str] = []
        self.connections = 0
        self.error: str | None = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=20)

    def _run(self):
        while not self.stop.is_set():
            headers = {"Last-Event-ID": str(self.last_id)} if self.last_id else {}
            try:
                with requests.get(self.url, cookies=self.cookies, headers=headers,
                                  stream=True, timeout=(5, 12)) as response:
                    response.raise_for_status()
                    self.connections += 1
                    event_type = None
                    event_id = None
                    for raw in response.iter_lines(chunk_size=1, decode_unicode=True):
                        if self.stop.is_set():
                            return
                        line = raw or ""
                        if line.startswith("id:"):
                            event_id = int(line.split(":", 1)[1].strip())
                        elif line.startswith("event:"):
                            event_type = line.split(":", 1)[1].strip()
                        elif line == "" and event_id is not None:
                            if event_id > self.last_id:
                                self.last_id = event_id
                                if event_type:
                                    self.types.append(event_type)
                            event_id = None
                            event_type = None
            except Exception as exc:
                self.error = str(exc)
                time.sleep(0.5)


def require(response: requests.Response, expected=(200, 202)) -> dict:
    if response.status_code not in expected:
        raise RuntimeError(f"HTTP {response.status_code} {response.url}: {response.text[:500]}")
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--compose-project", default="908c31a")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    base = args.base.rstrip("/")
    suffix = uuid.uuid4().hex[:10]
    password = f"Rc-{suffix}-Pass9"
    sessions = {"A": requests.Session(), "B": requests.Session()}
    users = {}
    initial_wallets = {}
    for label in ("A", "B"):
        payload = {"email": f"rc-{suffix}-{label.lower()}@example.com",
                   "password": password, "display_name": f"RC User {label}"}
        body = require(sessions[label].post(f"{base}/api/auth/register", json=payload))
        users[label] = body["user"]
        initial_wallets[label] = body["wallet"]["balance"]

    subprocess.run(["docker", "compose", "-p", args.compose_project, "stop", "worker"], check=True)
    requests_payload = {
        "A": {"topic": "人工智能如何帮助普通人提高工作效率", "mode": "auto",
              "persona": "深度观察者", "theme": "default", "idempotency_key": f"rc-{suffix}-auto"},
        "B": {"topic": "中年人如何建立更稳定的生活节奏", "mode": "interactive",
              "persona": "深度观察者", "theme": "default", "idempotency_key": f"rc-{suffix}-interactive"},
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {label: pool.submit(sessions[label].post, f"{base}/api/workflows",
                                      json=requests_payload[label], timeout=30)
                   for label in ("A", "B")}
        created = {label: require(future.result()) for label, future in futures.items()}
    workflow_ids = {label: created[label]["workflow"]["id"] for label in ("A", "B")}
    queued_before_worker = {label: created[label]["workflow"]["status"] for label in ("A", "B")}

    sse = {label: SSEProbe(base, workflow_ids[label], sessions[label].cookies.get_dict()) for label in ("A", "B")}
    for probe in sse.values():
        probe.start()
    subprocess.run(["docker", "compose", "-p", args.compose_project, "start", "worker"], check=True)
    time.sleep(3)
    subprocess.run(["docker", "compose", "-p", args.compose_project, "restart", "web"], check=True)

    decisions = []
    deadline = time.time() + args.timeout
    snapshots = {}
    last_progress = {"A": None, "B": None}
    while time.time() < deadline:
        for label in ("A", "B"):
            try:
                workflow = require(sessions[label].get(
                    f"{base}/api/workflows/{workflow_ids[label]}", timeout=15))["workflow"]
            except Exception:
                continue
            snapshots[label] = workflow
            progress = (workflow["status"], workflow["current_node"], workflow["version"])
            last_progress[label] = progress
            if label == "B" and workflow["status"] == "awaiting_input":
                node = workflow["current_node"]
                decision = {"topic": {"selection": 1}, "strategy": {"approved": True},
                            "visual": {"image_policy": "none"}}[node]
                response = sessions[label].post(f"{base}/api/workflows/{workflow_ids[label]}/decisions",
                                                json={"node": node, "expected_version": workflow["version"],
                                                      "decision": decision}, timeout=30)
                require(response)
                decisions.append(node)
        if len(snapshots) == 2 and all(snapshots[x]["status"] in TERMINAL for x in ("A", "B")):
            break
        time.sleep(1)
    else:
        raise RuntimeError(f"workflow timeout: {last_progress}")

    for probe in sse.values():
        probe.close()

    subprocess.run(["docker", "compose", "-p", args.compose_project, "restart", "web"], check=True)
    time.sleep(4)
    refreshed = {label: require(sessions[label].get(f"{base}/api/workflows/{workflow_ids[label]}", timeout=15))["workflow"]
                 for label in ("A", "B")}
    cross_status = {
        "B_reads_A": sessions["B"].get(f"{base}/api/workflows/{workflow_ids['A']}", timeout=15).status_code,
        "A_reads_B": sessions["A"].get(f"{base}/api/workflows/{workflow_ids['B']}", timeout=15).status_code,
        "B_events_A": sessions["B"].get(f"{base}/api/workflows/{workflow_ids['A']}/events", timeout=15).status_code,
    }
    wallets = {label: require(sessions[label].get(f"{base}/api/wallet", timeout=15))["wallet"]
               for label in ("A", "B")}
    subprocess.run(["docker", "compose", "-p", args.compose_project, "restart", "worker"], check=True)

    article_ok = {
        label: bool((refreshed[label].get("state") or {}).get("article"))
        for label in ("A", "B")
    }
    checks = {
        "queued_while_worker_down": all(value == "queued" for value in queued_before_worker.values()),
        "auto_completed": refreshed["A"]["status"] == "completed",
        "interactive_completed": refreshed["B"]["status"] == "completed",
        "interactive_waiting_and_resumed": decisions == ["topic", "strategy", "visual"],
        "article_results": all(article_ok.values()),
        "sse_events": all(probe.last_id > 0 and "workflow.completed" in probe.types for probe in sse.values()),
        "sse_reconnected": all(probe.connections >= 2 for probe in sse.values()),
        "refresh_recovery": all(refreshed[x]["status"] == "completed" for x in ("A", "B")),
        "authorization": all(code == 404 for code in cross_status.values()),
        "wallet_debited_once": all(wallets[x]["balance"] == initial_wallets[x] - 30 for x in ("A", "B")),
    }
    output = {"users": users, "workflow_ids": workflow_ids,
              "queued_before_worker": queued_before_worker, "decisions": decisions,
              "final": {x: {"status": refreshed[x]["status"], "node": refreshed[x]["current_node"],
                              "version": refreshed[x]["version"], "article": article_ok[x]}
                        for x in ("A", "B")},
              "sse": {x: {"last_id": sse[x].last_id, "connections": sse[x].connections,
                            "events": sse[x].types, "last_error": sse[x].error}
                      for x in ("A", "B")},
              "wallets": {x: {"initial": initial_wallets[x], "final": wallets[x]["balance"]}
                          for x in ("A", "B")},
              "cross_user_status": cross_status, "checks": checks,
              "passed": all(checks.values())}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not output["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
