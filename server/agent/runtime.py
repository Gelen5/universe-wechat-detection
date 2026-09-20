"""Production assembly for the normalized Agent runtime.

This module is imported by Celery workers as well as the Web process.  It only
assembles existing services; durable state continues to live in PostgreSQL.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from typing import Any, Callable

from .. import accounts, conversation_repository, creator_tools, diagnosis_service, image_provider, workbench
from ..providers import ModelService, OpenAICompatibleProvider, ProviderRequestError
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
        api_key=text_key,
        base_url=base,
        text_model=_configured("WECHAT_TEXT_MODEL", stored, "text_model", "gpt-4.1-mini"),
        image_api_key=image_key,
        image_base_url=image_base,
        image_model=_configured("WECHAT_IMAGE_MODEL", stored, "image_model", "gpt-image-2"),
        verify_ssl=os.getenv("WECHAT_API_VERIFY_SSL", "true").lower() not in {"0", "false", "no", "off"},
    )
    def record_usage(values):
        payload = dict(values)
        conversation_repository.record_provider_call(
            payload.pop("run_id"), payload.pop("user_id"), **payload)

    return ModelService(provider, usage_recorder=record_usage)


def _required_text(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _with_provider(call: Callable[[], dict[str, Any] | list | str]):
    with workbench.provider_overrides():
        return call()


def _wechat_tools(*, model_service: ModelService | None = None,
                  run_id: str | None = None, user_id: str | None = None) -> dict[str, Callable[[dict[str, Any]], Any]]:
    def search_topics(args):
        topic = _required_text(args, "topic")
        persona = str(args.get("persona") or "深度观察者")
        return _with_provider(lambda: {"topics": workbench._suggestions(topic, persona)})

    def write_article(args):
        title = str(args.get("title") or args.get("topic") or "").strip()
        if not title:
            raise ValueError("title or topic is required")
        persona = str(args.get("persona") or "深度观察者")
        requirements = str(args.get("requirements") or "")
        frame = args.get("framework")
        if not isinstance(frame, dict) or not frame.get("outline"):
            frame = _with_provider(lambda: workbench._framework(title, persona, requirements))
        return _with_provider(lambda: {"title": title, "article": workbench._draft(
            title, frame, persona, requirements)})

    def revise_article(args):
        article = _required_text(args, "article")
        requirements = _required_text(args, "requirements")
        if model_service is None:
            raise RuntimeError("revise_article requires the normalized ModelService")
        response = model_service.create_response([
            {"role": "system", "content": "你是公众号编辑。严格基于原文执行用户修改要求，保留未要求修改的事实、结构和内容，只输出修改后的完整正文。"},
            {"role": "user", "content": f"修改要求：\n{requirements}\n\n原文：\n{article}"},
        ], timeout=180, idempotency_key=f"{run_id}:revise_article",
           run_id=run_id, user_id=user_id)
        return {"title": str(args.get("title") or "修订稿"), "article": response.text}

    def generate_image(args):
        prompt = _required_text(args, "prompt")
        size = str(args.get("size") or "1024x1024")
        count = int(args.get("count") or 1)
        if model_service is not None:
            request_hash = hashlib.sha256(
                f"{prompt}\0{size}\0{count}".encode("utf-8")
            ).hexdigest()[:24]
            return model_service.generate_image(
                prompt, size=size, count=count,
                idempotency_key=f"{run_id}:generate_image:{request_hash}",
                run_id=run_id, user_id=user_id,
            )
        payload = {"prompt": prompt, "size": size, "n": count}
        return _with_provider(lambda: image_provider.generate(payload))

    def typeset_article(args):
        article = _required_text(args, "article")
        session = {
            "id": uuid.uuid4().hex, "article": article,
            "theme": str(args.get("theme") or "default"), "image_plan": {}, "images": [],
            "skill_runs": [], "brief": str(args.get("requirements") or ""),
            "typeset_html": "", "preview_document": "",
        }
        html = _with_provider(lambda: workbench._typeset(session))
        return {"html": html, "preview_document": session.get("preview_document", "")}

    return {"search_topics": search_topics, "write_article": write_article,
            "revise_article": revise_article,
            "generate_image": generate_image, "typeset_article": typeset_article}


def _creator_draft(skill_id: str, args: dict[str, Any]) -> dict[str, Any]:
    if skill_id == "xiaohongshu_creator":
        values = {"topic": _required_text(args, "topic"), "account": str(args.get("account") or ""),
                  "audience": str(args.get("audience") or ""), "goal": str(args.get("goal") or "建立信任"),
                  "evidence": str(args.get("evidence") or ""), "content_type": str(args.get("content_type") or ""),
                  "image_count": int(args.get("image_count", 6)), "requirements": str(args.get("requirements") or "")}
        return _with_provider(lambda: creator_tools.xiaohongshu_package(**values))
    if skill_id == "morning_blessing":
        values = {"topic": str(args.get("topic") or "早安祝福"), "image_count": int(args.get("image_count", 4)),
                  "copy_count": int(args.get("copy_count", 3)), "style": str(args.get("style") or ""),
                  "mode": str(args.get("mode") or "article"), "columns": int(args.get("columns", 1)),
                  "image_at": int(args.get("image_at", 1)), "image_position": str(args.get("image_position") or "after"),
                  "size": str(args.get("size") or "768x1024"), "requirements": str(args.get("requirements") or "")}
        return _with_provider(lambda: creator_tools.morning_draft(**values))
    values = {"industry": str(args.get("industry") or ""), "topic": _required_text(args, "topic"),
              "title": str(args.get("title") or ""), "content_type": args.get("content_type"),
              "image_count": int(args.get("image_count", 4)), "style": str(args.get("style") or ""),
              "audience": str(args.get("audience") or ""), "portrait_mode": str(args.get("portrait_mode") or ""),
              "requirements": str(args.get("requirements") or "")}
    return _with_provider(lambda: creator_tools.tie_tu_plan(**values))


def _skill_executors(skill_id: str, *, model_service: ModelService | None = None,
                     run_id: str | None = None,
                     user_id: str | None = None) -> dict[str, Callable[[dict[str, Any]], Any]]:
    if skill_id == "wechat_writer":
        return _wechat_tools(model_service=model_service, run_id=run_id, user_id=user_id)
    if skill_id == "wechat_account_analyzer":
        return {"diagnose_account": lambda args: diagnosis_service.run(
            _required_text(args, "account_name"), lambda report: report)}
    if skill_id == "wechat_hit_detector":
        return {
            "review_article": lambda args: creator_tools.detect_article(
                str(args.get("title") or ""), _required_text(args, "body"), str(args.get("track") or "auto")),
            "rewrite_article": lambda args: _with_provider(lambda: creator_tools.rewrite_article(
                str(args.get("title") or ""), _required_text(args, "body"),
                args.get("detector_result") if isinstance(args.get("detector_result"), dict)
                else creator_tools.detect_article(str(args.get("title") or ""), _required_text(args, "body")))),
        }
    if skill_id in {"xiaohongshu_creator", "morning_blessing", "wechat_tie_tu"}:
        tools: dict[str, Callable[[dict[str, Any]], Any]] = {
            "generate_draft": lambda args: _creator_draft(skill_id, args),
        }
        if skill_id == "morning_blessing":
            tools["change_layout"] = lambda args: {"changed": args, "text_preserved": True,
                                                     "images_preserved": True}

        def generate_images(args):
            draft = args.get("draft")
            if not isinstance(draft, dict) or not isinstance(draft.get("cards"), list):
                raise ValueError("draft with cards is required")
            style = str(args.get("style") or "")
            tool = "xiaohongshu" if skill_id == "xiaohongshu_creator" else "tie-tu"
            return {"images": [_with_provider(lambda card=card: creator_tools.generate_card_image(
                tool, str(draft.get("session_id") or uuid.uuid4().hex), card, style,
                size=str(args.get("size") or draft.get("size") or "768x1024")))
                for card in draft["cards"]]}
        tools["generate_images"] = generate_images
        return tools
    return {}


def resolve_tools(skill_id: str, *, registry: SkillRegistry | None = None,
                  model_service: ModelService | None = None,
                  run_id: str | None = None,
                  user_id: str | None = None) -> dict[str, ExecutableTool]:
    manifest = (registry or get_registry()).executable(skill_id)
    executors = _skill_executors(
        skill_id, model_service=model_service, run_id=run_id, user_id=user_id,
    )
    resolved: dict[str, ExecutableTool] = {}
    for tool in manifest.tools:
        execute = executors.get(tool.name)
        if execute is None:
            raise RuntimeError(f"Skill tool is not registered: {skill_id}.{tool.name}")
        resolved[tool.name] = ExecutableTool(
            {"name": tool.name, "description": tool.description, "parameters": tool.parameters}, execute)
    return resolved


def build_orchestrator() -> AgentOrchestrator:
    registry = get_registry()
    model_service = build_model_service()
    return AgentOrchestrator(
        registry=registry,
        model_service=model_service,
        tool_resolver=lambda skill_id, run_id, user_id: resolve_tools(
            skill_id, registry=registry, model_service=model_service,
            run_id=run_id, user_id=user_id,
        ),
    )
