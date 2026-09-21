from __future__ import annotations

import json
from typing import Callable

from .. import conversation_repository
from ..agent_events import notify
from ..providers import ModelService, ProviderRequestError
from ..skills.registry import SkillRegistry
from ..skills.runtime import load_instructions
from ..skills.tool_result import ArtifactOutput, ToolResult
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

    def _persist_tool_artifacts(self, run_id: str, user_id: str,
                                outputs: tuple[ArtifactOutput, ...], tool_call_id: str) -> list[dict]:
        artifacts: list[dict] = []
        for index, output in enumerate(outputs):
            if output.type == "image":
                payload = output.content_json
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
                        run_id, user_id, output.type, title=output.title,
                        content=output.content, content_json=metadata, storage_key=stored.key,
                        storage_url=stored.url,
                        source_key=f"{tool_call_id}:{output.type}:{index}",
                    ))
                    continue
            storage_url = output.storage_url
            if output.type == "image" and not storage_url:
                storage_url = str(output.content_json.get("local_url") or
                                  output.content_json.get("path") or
                                  output.content_json.get("url") or "") or None
            artifacts.append(conversation_repository.create_artifact(
                run_id, user_id, output.type, title=output.title,
                content=output.content, content_json=output.content_json,
                storage_url=storage_url,
                source_key=f"{tool_call_id}:{output.type}:{index}",
            ))
        return artifacts

    @staticmethod
    def _compact_tool_result(result: ToolResult, artifacts: list[dict]) -> dict:
        compact = dict(result.data)
        images = [item for item in artifacts if item.get("type") == "image"]
        if not images:
            return compact
        compact.pop("data", None)
        compact["images"] = [{
            "artifact_id": item["id"], "storage_url": item.get("storage_url"),
            "storage_key": item.get("storage_key"), "title": item.get("title"),
        } for item in images]
        return compact

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

            def persist_result(result: ToolResult, tool_call_id: str) -> dict:
                created = self._persist_tool_artifacts(
                    run_id, user_id, result.artifacts, tool_call_id,
                )
                tool_artifacts.extend(created)
                return self._compact_tool_result(result, created)

            answer = run_tool_loop(
                model_service=self.model_service,
                messages=[{"role": "system", "content": instructions}, *history],
                tools=self.tool_resolver(decision.skill_id, run_id, user_id),
                run_id=run_id, user_id=user_id,
                skill_id=decision.skill_id,
                max_tool_calls=int(manifest.limits.get("max_tool_calls", 12)),
                timeout_seconds=int(manifest.limits.get("timeout_seconds", 600)),
                is_cancelled=(lambda: not conversation_repository.run_lease_owned(run_id, task_id)) if task_id else (lambda: False),
                heartbeat=(lambda: conversation_repository.heartbeat_run(run_id, task_id)) if task_id else (lambda: True),
                on_tool_result=persist_result,
            )
            if task_id and not conversation_repository.heartbeat_run(run_id, task_id):
                raise RuntimeError("run execution lease changed")
            message = conversation_repository.add_message(conversation["id"], user_id, "assistant", answer)
            if tool_artifacts:
                artifact = tool_artifacts[-1]
            else:
                artifact_type = str(manifest.runtime.get("default_artifact") or "article")
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
