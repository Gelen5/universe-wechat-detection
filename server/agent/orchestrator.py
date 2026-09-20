from __future__ import annotations

import json
from typing import Callable

from .. import conversation_repository
from ..agent_events import notify
from ..providers import ModelService, ProviderRequestError
from ..skills.registry import SkillRegistry
from ..skills.runtime import load_instructions
from ..storage.image_ingest import ingest_generated_image
from .context import conversation_messages
from .router import SkillRouter
from .tool_loop import ExecutableTool, run_tool_loop


class AgentOrchestrator:
    def __init__(self, *, registry: SkillRegistry, model_service: ModelService,
                 tool_resolver: Callable[[str, str, str], dict[str, ExecutableTool]]):
        self.registry = registry
        self.model_service = model_service
        self.tool_resolver = tool_resolver

    @staticmethod
    def _text(value) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, indent=2)

    def _persist_tool_artifacts(self, run_id: str, user_id: str, tool_name: str,
                                result: dict, tool_call_id: str) -> list[dict]:
        artifacts: list[dict] = []

        def save(artifact_type: str, *, title: str = "", content="",
                 content_json: dict | None = None, storage_url: str | None = None,
                 index: int = 0) -> None:
            artifacts.append(conversation_repository.create_artifact(
                run_id, user_id, artifact_type, title=title,
                content=self._text(content), content_json=content_json or result,
                storage_url=storage_url,
                source_key=f"{tool_call_id}:{artifact_type}:{index}",
            ))

        if tool_name == "search_topics":
            topics = result.get("topics", result)
            if isinstance(topics, list):
                lines = []
                for index, topic in enumerate(topics, 1):
                    title = topic.get("title") if isinstance(topic, dict) else str(topic)
                    lines.append(f"{index}. {title or ''}")
                content = "\n".join(lines)
            else:
                content = topics
            save("topic", title="选题建议", content=content)
        elif tool_name in {"write_article", "revise_article", "generate_draft"}:
            content = result.get("article") or result.get("body") or result.get("content") or result
            title = str(result.get("title") or "创作稿件")
            save("article", title=title, content=content)
        elif tool_name in {"typeset_article", "change_layout"}:
            content = result.get("preview_document") or result.get("html") or result
            save("html", title="排版结果", content=content)
        elif tool_name in {"review_article", "rewrite_article", "diagnose_account"}:
            content = result.get("article") or result.get("report") or result.get("content") or result
            save("report", title="分析报告", content=content)
        elif tool_name in {"generate_image", "generate_images"}:
            values = result.get("images") or result.get("data") or []
            if isinstance(values, dict):
                values = [values]
            for index, item in enumerate(values if isinstance(values, list) else []):
                payload = item if isinstance(item, dict) else {"url": str(item)}
                if payload.get("b64_json") or payload.get("image_url") or (
                    isinstance(payload.get("url"), str) and payload["url"].startswith("https://")
                ):
                    stored = ingest_generated_image(
                        payload, f"{user_id}/{run_id}/{tool_call_id}-{index + 1}",
                    )
                    metadata = {key: value for key, value in payload.items() if key != "b64_json"}
                    metadata["file"] = {
                        "content_type": stored.content_type, "size": stored.size,
                    }
                    artifacts.append(conversation_repository.create_artifact(
                        run_id, user_id, "image", title=f"生成图片 {index + 1}",
                        content="", content_json=metadata, storage_key=stored.key,
                        storage_url=stored.url,
                        source_key=f"{tool_call_id}:image:{index}",
                    ))
                else:
                    url = payload.get("local_url") or payload.get("path") or payload.get("url")
                    save("image", title=f"生成图片 {index + 1}", content=payload,
                         content_json=payload, storage_url=str(url) if url else None, index=index)
        return artifacts

    def execute(self, run_id: str, user_id: str, *, task_id: str | None = None) -> dict:
        run = conversation_repository.get_run(run_id, user_id)
        if not run:
            raise KeyError("run not found")
        conversation = conversation_repository.get_conversation(run["conversation_id"], user_id)
        if not conversation:
            raise KeyError("conversation not found")
        history = conversation_messages(conversation["id"], user_id)
        trigger = next(item["content"] for item in reversed(history) if item["role"] == "user")
        decision = SkillRouter(self.registry, self.model_service).route(
            trigger, mode=conversation["mode"], bound_skill_id=conversation["skill_id"],
            run_id=run_id, user_id=user_id)
        if decision.needs_confirmation or not decision.skill_id:
            conversation_repository.transition_run(run_id, user_id, "waiting_input", task_id=task_id)
            message = conversation_repository.add_message(conversation["id"], user_id, "assistant",
                "我还不能确定该使用哪项能力，请补充你要完成的作品类型。")
            return {"status": "waiting_input", "message": message, "route": decision}
        manifest = self.registry.executable(decision.skill_id)
        conversation_repository.bind_run_skill(
            run_id, user_id, decision.skill_id, task_id=task_id,
        )
        if conversation["mode"] == "auto" and conversation.get("skill_id") != decision.skill_id:
            conversation = conversation_repository.bind_conversation_skill(
                conversation["id"], user_id, decision.skill_id,
            )
        conversation_repository.record_run_event(run_id, user_id, "skill.selected", {
            "skill_id": decision.skill_id, "confidence": decision.confidence,
            "reason": decision.reason,
        })
        notify(run_id)
        instructions, _ = load_instructions(decision.skill_id, registry=self.registry)
        if run["status"] == "queued":
            conversation_repository.transition_run(run_id, user_id, "running", task_id=task_id)
        try:
            tool_artifacts: list[dict] = []

            def persist_result(tool_name: str, result: dict, tool_call_id: str) -> None:
                tool_artifacts.extend(self._persist_tool_artifacts(
                    run_id, user_id, tool_name, result, tool_call_id,
                ))

            answer = run_tool_loop(
                model_service=self.model_service,
                messages=[{"role": "system", "content": instructions}, *history],
                tools=self.tool_resolver(decision.skill_id, run_id, user_id),
                run_id=run_id, user_id=user_id,
                skill_id=decision.skill_id,
                max_tool_calls=int(manifest.limits.get("max_tool_calls", 12)),
                timeout_seconds=int(manifest.limits.get("timeout_seconds", 600)),
                is_cancelled=(lambda: not conversation_repository.run_lease_owned(run_id, task_id)) if task_id else (lambda: False),
                on_tool_result=persist_result,
            )
            if task_id and not conversation_repository.heartbeat_run(run_id, task_id):
                raise RuntimeError("run execution lease changed")
            message = conversation_repository.add_message(conversation["id"], user_id, "assistant", answer)
            if tool_artifacts:
                artifact = tool_artifacts[-1]
            else:
                artifact_type = "report" if ({"report", "account_analysis", "review", "risk_check"}
                                             & set(manifest.capabilities)) else "article"
                artifact = conversation_repository.create_artifact(
                    run_id, user_id, artifact_type, title=conversation["title"], content=answer,
                    content_json={"skill_id": decision.skill_id},
                    source_key=f"{run_id}:final",
                )
            conversation_repository.record_run_event(run_id, user_id, "assistant.completed", {
                "message_id": message["id"], "artifact_id": artifact["id"],
            })
            conversation_repository.transition_run(run_id, user_id, "completed", task_id=task_id)
            notify(run_id)
            return {"status": "completed", "message": message, "artifact": artifact, "route": decision}
        except ProviderRequestError as exc:
            if exc.transient:
                raise
            conversation_repository.transition_run(
                run_id, user_id, "failed", error_code=exc.code,
                error_message=str(exc), task_id=task_id,
            )
            notify(run_id)
            raise
        except Exception as exc:
            conversation_repository.transition_run(run_id, user_id, "failed",
                                                   error_code=type(exc).__name__, error_message=str(exc), task_id=task_id)
            notify(run_id)
            raise
