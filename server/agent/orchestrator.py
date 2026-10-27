from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import Callable

from .. import conversation_repository
from ..agent_events import notify
from ..providers import ModelService, ProviderRequestError
from .failures import fail_run
from ..skills.registry import SkillRegistry
from ..skills.runtime import load_instructions
from ..skills.tool_result import ArtifactOutput, ToolResult
from ..storage.image_ingest import ingest_generated_image
from .context import conversation_messages, stage_messages
from .failures import fail_run
from .intent import resolve_intent
from .router import SkillRouter
from .tool_loop import ExecutableTool, run_tool_loop


WECHAT_STAGE_TO_TOOL = {
    "topic": "search_topics",
    "outline": "create_outline",
    "writing": "write_article",
    "deai": "review_article",
    "typeset": "typeset_article",
}

STAGE_LABELS = {
    "topic": "选题", "outline": "大纲", "writing": "写作",
    "deai": "去 AI 复核", "typeset": "排版",
}

STAGE_REQUIREMENTS = {
    "topic": "围绕用户方向生成 10 个差异明显、能真正展开的公众号选题；"
             "不写正文、不生成配图、不排版，也不要重复历史选题。",
    "outline": "为下面已确认的选题生成可编辑的公众号大纲；只输出结构，不写正文。",
    "writing": "按已确认的大纲写完整公众号正文；不配图、不排版，不改动选题方向。",
    "deai": "只对当前最新正文做事实边界与表达复核并保存修订稿；不改选题、不掉事实、不改结构。",
    "typeset": "只用当前最新正文生成公众号 HTML；不改写正文、不配图，不新增事实。",
}


def stage_contract(stage: str, tool: str, content_json: dict) -> str:
    """Server-side stage prompt so the composer can stay a plain chat box."""
    label = STAGE_LABELS.get(stage, stage)
    direction = str(content_json.get("topic_direction") or "").strip()
    selected = str(content_json.get("selected_topic") or "").strip()
    lines = [
        f"当前只执行公众号创作的「{label}」阶段（workflow_stage={stage}）。",
        f"必须调用 {tool} 工具一次，不要调用其它阶段的工具，不要生成图片。",
    ]
    if direction:
        lines.append(f"用户本轮方向：{direction}")
    if selected:
        lines.append(f"已确认选题：{selected}")
    lines.append(f"阶段要求：{STAGE_REQUIREMENTS.get(stage, '只完成当前阶段。')}")
    lines.append("完成后只用一句话说明本阶段结果，不要在回复里重复整篇作品。")
    return "\n".join(lines)


class AgentOrchestrator:
    def __init__(self, *, registry: SkillRegistry, model_service: ModelService,
                 tool_resolver: Callable[[str, str, str], dict[str, ExecutableTool]],
                 intent_service: ModelService | None = None):
        self.registry = registry
        self.model_service = model_service
        # Routing is a tiny classification call: a faster/cheaper model can be
        # configured for it without changing the writing model.
        self.intent_service = intent_service or model_service
        self.tool_resolver = tool_resolver

    @staticmethod
    def _text(value) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, indent=2)

    def _persist_tool_artifacts(self, run_id: str, user_id: str,
                                outputs: tuple[ArtifactOutput, ...], tool_call_id: str,
                                task_id: str | None = None) -> list[dict]:
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
                        task_id=task_id,
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
                task_id=task_id,
            ))
        return artifacts

    @staticmethod
    def _compact_tool_result(result: ToolResult, artifacts: list[dict]) -> dict:
        compact = dict(result.data)
        html_artifacts = [item for item in artifacts if item.get("type") == "html"]
        if html_artifacts:
            compact.pop("html", None)
            compact.pop("preview_document", None)
            compact["html_artifact_id"] = html_artifacts[-1]["id"]
            compact["html_chars"] = len(html_artifacts[-1].get("content") or "")
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
        history = conversation_messages(conversation["id"], user_id, run_id=run_id)
        trigger_message = conversation_repository.get_message(
            conversation["id"], user_id, run["trigger_message_id"])
        if not trigger_message:
            raise KeyError("trigger message not found")
        trigger = trigger_message["content"]
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
        content_json = (trigger_message.get("content_json") or {}) if isinstance(
            trigger_message.get("content_json"), dict) else {}
        hint = content_json.get("workflow_stage")
        # Only the workbench is stage-based. Anything else (auto chat, other
        # callers) keeps the original free-form behaviour: all tools available.
        workbench = isinstance(hint, str) and hint in WECHAT_STAGE_TO_TOOL
        intent = None
        stage = None
        direction = ""
        selected_topic = ""
        if workbench:
            # The tab is a hint, not a decision: one model call reads the message
            # and the workbench state, then tells us which stage (if any) to run.
            intent = resolve_intent(
                model_service=self.intent_service,
                text=trigger,
                stage_hint=hint,
                artifacts=conversation_repository.run_inputs(run_id, user_id, messages=False)['artifacts'],
                recent=history,
                run_id=run_id, user_id=user_id,
                explicit_stage=hint if content_json.get("stage_explicit") else None,
            )
            stage = intent.stage
            direction = str(content_json.get("topic_direction") or intent.direction or "")
            selected_topic = str(content_json.get("selected_topic") or intent.selected_topic or "")
            conversation_repository.set_run_stage(run_id, user_id, stage, task_id=task_id)
            if intent.source != "explicit":
                # Explicit clicks already know their stage; only announce model decisions.
                conversation_repository.record_run_event(run_id, user_id, "stage.resolved", {
                    "stage": stage, "reason": intent.reason, "source": intent.source,
                    "confidence": round(intent.confidence, 3),
                    "direction": direction, "selected_topic": selected_topic,
                })
                if stage != hint:
                    # Make the reasoning durable: the thread keeps "已理解…" even
                    # after a refresh, so a tab switch is never unexplained.
                    conversation_repository.add_message(
                        conversation["id"], user_id, "assistant",
                        f"已理解：{intent.reason}",
                        content_json={"kind": "stage_note", "stage": stage})
                notify(run_id)
        if run["status"] == "queued":
            conversation_repository.transition_run(run_id, user_id, "running", task_id=task_id)
        try:
            tool_artifacts: list[dict] = []

            def persist_result(result: ToolResult, tool_call_id: str) -> dict:
                created = self._persist_tool_artifacts(
                    run_id, user_id, result.artifacts, tool_call_id, task_id=task_id,
                )
                tool_artifacts.extend(created)
                return self._compact_tool_result(result, created)

            is_cancelled = (lambda: not conversation_repository.run_lease_owned(run_id, task_id)) if task_id else (lambda: False)
            heartbeat = (lambda: conversation_repository.heartbeat_run(run_id, task_id)) if task_id else (lambda: True)
            if manifest.runtime.get("engine") == "easel_native":
                from ..integrations.easel.harness import UniverseNativeHarness
                from ..integrations.easel.harness.schemas import RunContext
                from ..integrations.easel.native.catalog import skill_loader
                skill = skill_loader().load(manifest.root.name)
                metadata = conversation.get("metadata") or {}
                profile = metadata.get("profile") if isinstance(metadata, dict) else None
                context = RunContext(
                    user_id=user_id, run_id=run_id, conversation_id=conversation["id"],
                    workspace=Path(__file__).resolve().parents[2],
                    output_dir=Path(__file__).resolve().parents[2] / "output" / run_id,
                    timeout_seconds=int(manifest.limits.get("timeout_seconds", 300)),
                    history=history[:-1], is_cancelled=is_cancelled, heartbeat=heartbeat,
                )
                result = asyncio.run(UniverseNativeHarness(self.model_service).execute(
                    run_context=context, skill=skill, input_data=trigger,
                    profile=profile if isinstance(profile, dict) else {},
                    attachments=[], tools=self.tool_resolver(decision.skill_id, run_id, user_id),
                ))
                answer = result.text
            else:
                tools = self.tool_resolver(decision.skill_id, run_id, user_id)
                required_tool = (WECHAT_STAGE_TO_TOOL.get(stage)
                                 if workbench and decision.skill_id == "wechat_writer"
                                 and stage in WECHAT_STAGE_TO_TOOL else None)
                if workbench:
                    # Only the resolved stage's inputs are sent (server/agent/context.py).
                    history = stage_messages(conversation["id"], user_id, stage=stage, run_id=run_id)
                    if stage is None:
                        # The user asked a question instead of asking for a stage:
                        # answer it, do not run a tool or mint an artifact.
                        tools = {}
                    elif required_tool:
                        if required_tool not in tools:
                            raise RuntimeError(f"Skill stage tool unavailable: {required_tool}")
                        tools = {required_tool: tools[required_tool]}
                        history.insert(0, {"role": "system", "content":
                                           stage_contract(stage, required_tool, {
                                               "topic_direction": direction,
                                               "selected_topic": selected_topic,
                                           })})
                answer = run_tool_loop(
                    model_service=self.model_service,
                    messages=[{"role": "system", "content": instructions}, *history],
                    tools=tools,
                    run_id=run_id, user_id=user_id,
                    skill_id=decision.skill_id,
                    max_tool_calls=int(manifest.limits.get("max_tool_calls", 12)),
                    timeout_seconds=int(manifest.limits.get("timeout_seconds", 600)),
                    is_cancelled=is_cancelled, heartbeat=heartbeat,
                    on_tool_result=persist_result,
                    required_tool=required_tool,
                )
                if workbench and stage is None and not answer.strip():
                    answer = "我没看懂这句话要做什么。可以点上面五个阶段之一，或直接说「给我选题」「开始写正文」「排版」。"
            if task_id and not conversation_repository.heartbeat_run(run_id, task_id):
                raise RuntimeError("run execution lease changed")
            message = conversation_repository.add_message(
                conversation["id"], user_id, "assistant", answer,
                content_json={"kind": "answer"} if workbench and stage is None else None)
            if tool_artifacts:
                artifact = tool_artifacts[-1]
            elif workbench and stage is None:
                artifact = None
            else:
                artifact_type = str(manifest.runtime.get("default_artifact") or "article")
                artifact = conversation_repository.create_artifact(
                    run_id, user_id, artifact_type, title=conversation["title"], content=answer,
                    content_json={"skill_id": decision.skill_id},
                    source_key=f"{run_id}:final",
                    task_id=task_id,
                )
            conversation_repository.record_run_event(run_id, user_id, "assistant.completed", {
                "message_id": message["id"],
                "artifact_id": artifact["id"] if artifact else None,
            })
            conversation_repository.transition_run(run_id, user_id, "completed", task_id=task_id)
            notify(run_id)
            return {"status": "completed", "message": message, "artifact": artifact, "route": decision}
        except ProviderRequestError as exc:
            if exc.transient:
                raise
            fail_run(run_id, user_id, exc, task_id=task_id)
            notify(run_id)
            raise
        except Exception as exc:
            fail_run(run_id, user_id, exc, task_id=task_id)
            notify(run_id)
            raise
