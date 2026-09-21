"""Production assembly for the normalized, manifest-driven Agent runtime."""
from __future__ import annotations

import os
from typing import Any

from .. import accounts, conversation_repository
from ..providers import ModelService, OpenAICompatibleProvider, ProviderCostPolicy, ProviderRequestError
from ..skills.executor_registry import get_executor_registry
from ..skills.registry import SkillRegistry, get_registry
from .orchestrator import AgentOrchestrator
from .tool_loop import ExecutableTool


def _configured(name: str, stored: dict[str, Any], key: str, default: str = "") -> str:
    return str(stored.get(key) or os.getenv(name) or default).strip()


def build_model_service() -> ModelService:
    stored = accounts.provider_settings(include_secrets=True)
    text_key = _configured("WECHAT_TEXT_API_KEY", stored, "text_api_key")
    if not text_key:
        raise ProviderRequestError("服务端尚未配置文字 API", code="provider_not_configured")
    base = _configured("WECHAT_TEXT_API_BASE_URL", stored, "text_base_url", "https://api.openai.com/v1")
    image_key = _configured("WECHAT_IMAGE_API_KEY", stored, "image_api_key") or text_key
    image_base = _configured("WECHAT_IMAGE_API_BASE_URL", stored, "image_base_url") or base
    provider = OpenAICompatibleProvider(
        api_key=text_key, base_url=base,
        text_model=_configured("WECHAT_TEXT_MODEL", stored, "text_model", "gpt-4.1-mini"),
        image_api_key=image_key, image_base_url=image_base,
        image_model=_configured("WECHAT_IMAGE_MODEL", stored, "image_model", "gpt-image-2"),
        verify_ssl=os.getenv("WECHAT_API_VERIFY_SSL", "true").lower() not in {"0", "false", "no", "off"},
    )

    def record_usage(values):
        payload = dict(values)
        conversation_repository.record_provider_call(
            payload.pop("run_id"), payload.pop("user_id"), **payload)

    return ModelService(provider, usage_recorder=record_usage, cost_policy=ProviderCostPolicy(
        input_micros_per_million_tokens=max(0, int(os.getenv(
            "WECHAT_TEXT_INPUT_MICROS_PER_MILLION_TOKENS", "0"))),
        output_micros_per_million_tokens=max(0, int(os.getenv(
            "WECHAT_TEXT_OUTPUT_MICROS_PER_MILLION_TOKENS", "0"))),
        image_micros_each=max(0, int(os.getenv("WECHAT_IMAGE_MICROS_EACH", "0"))),
    ))


def resolve_tools(skill_id: str, *, registry: SkillRegistry | None = None,
                  model_service: ModelService | None = None,
                  run_id: str | None = None,
                  user_id: str | None = None) -> dict[str, ExecutableTool]:
    manifest = (registry or get_registry()).executable(skill_id)
    executors = get_executor_registry().tools(manifest)
    resolved: dict[str, ExecutableTool] = {}
    for tool in manifest.tools:
        execute = executors.get(tool.executor)
        if execute is None:
            raise RuntimeError(f"Skill executor is not registered: {skill_id}.{tool.executor}")
        resolved[tool.name] = ExecutableTool(
            definition={"name": tool.name, "description": tool.description,
                        "parameters": tool.parameters},
            execute=execute,
            side_effect=tool.side_effect,
            requires_confirmation=tool.requires_confirmation,
        )
    return resolved


def build_orchestrator() -> AgentOrchestrator:
    registry = get_registry()
    model_service = build_model_service()
    return AgentOrchestrator(
        registry=registry, model_service=model_service,
        tool_resolver=lambda skill_id, run_id, user_id: resolve_tools(
            skill_id, registry=registry, model_service=model_service,
            run_id=run_id, user_id=user_id),
    )
