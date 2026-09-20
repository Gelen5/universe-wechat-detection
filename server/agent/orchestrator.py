from __future__ import annotations

from typing import Callable

from .. import conversation_repository
from ..providers import ModelService
from ..skills.registry import SkillRegistry
from ..skills.runtime import load_instructions
from .context import conversation_messages
from .router import SkillRouter
from .tool_loop import ExecutableTool, run_tool_loop


class AgentOrchestrator:
    def __init__(self, *, registry: SkillRegistry, model_service: ModelService,
                 tool_resolver: Callable[[str], dict[str, ExecutableTool]]):
        self.registry = registry
        self.model_service = model_service
        self.tool_resolver = tool_resolver

    def execute(self, run_id: str, user_id: str) -> dict:
        run = conversation_repository.get_run(run_id, user_id)
        if not run:
            raise KeyError("run not found")
        conversation = conversation_repository.get_conversation(run["conversation_id"], user_id)
        if not conversation:
            raise KeyError("conversation not found")
        history = conversation_messages(conversation["id"], user_id)
        trigger = next(item["content"] for item in reversed(history) if item["role"] == "user")
        decision = SkillRouter(self.registry, self.model_service).route(
            trigger, mode=conversation["mode"], bound_skill_id=conversation["skill_id"])
        if decision.needs_confirmation or not decision.skill_id:
            conversation_repository.transition_run(run_id, user_id, "waiting_input")
            message = conversation_repository.add_message(conversation["id"], user_id, "assistant",
                "我还不能确定该使用哪项能力，请补充你要完成的作品类型。")
            return {"status": "waiting_input", "message": message, "route": decision}
        manifest = self.registry.get(decision.skill_id)
        instructions, _ = load_instructions(decision.skill_id, registry=self.registry)
        if run["status"] == "queued":
            conversation_repository.transition_run(run_id, user_id, "running")
        try:
            answer = run_tool_loop(
                model_service=self.model_service,
                messages=[{"role": "system", "content": instructions}, *history],
                tools=self.tool_resolver(decision.skill_id), run_id=run_id, user_id=user_id,
                skill_id=decision.skill_id,
                max_tool_calls=int(manifest.limits.get("max_tool_calls", 12)),
                timeout_seconds=int(manifest.limits.get("timeout_seconds", 600)),
            )
            message = conversation_repository.add_message(conversation["id"], user_id, "assistant", answer)
            conversation_repository.transition_run(run_id, user_id, "completed")
            return {"status": "completed", "message": message, "route": decision}
        except Exception as exc:
            conversation_repository.transition_run(run_id, user_id, "failed",
                                                   error_code=type(exc).__name__, error_message=str(exc))
            raise
