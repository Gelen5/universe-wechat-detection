from __future__ import annotations

import uuid
import shutil

from server import conversation_repository
from server.skills.adapter_support import article_result, model_image, required_text, topics_result, with_provider
from server.skills.tool_result import ArtifactOutput, ToolResult
from server import workbench


def create_tools():
    def progress_for(context):
        """把节点内部进度写进 Run 事件流，前端才能显示"卡在哪一步"。"""
        def emit(step, detail=None):
            try:
                context.emit("tool.progress", {"step": step, **(detail or {})})
            except Exception:
                pass
        return emit

    def latest_artifact(context, artifact_type, items=None):
        if items is None:
            items = conversation_repository.list_artifacts(context.conversation_id, context.user_id)
        return max((item for item in items if item["type"] == artifact_type),
                   key=lambda item: (item.get("version", 0), item.get("created_at", "")), default=None)

    def search_topics(args, context):
        session = {}
        topics = with_provider(lambda: workbench._suggestions(
            required_text(args, "topic"), str(args.get("persona") or "深度观察者"), session,
            progress_for(context)))
        research = session.get("topic_research") or {}
        evidence = {
            "checked_at": research.get("checked_at"),
            "search_status": research.get("status", "unavailable"),
            "hotspot_status": session.get("hotspot_status", "unavailable"),
            "search_sources": [{
                "provider": source.get("provider", "search"),
                "title": source.get("title", ""),
                "url": source.get("url", ""),
                "published_at": source.get("published_at", ""),
                "verification": "search_excerpt_only",
            } for source in (research.get("sources") or [])[:10] if source.get("url", "").startswith("https://")],
            "platform_hotspots": [{
                "title": item.get("title", ""), "platforms": item.get("sources") or [],
            } for item in (session.get("skill_hotspots") or [])[:10] if item.get("title")],
        }
        return topics_result(topics, evidence)

    def create_outline(args, context):
        title = required_text(args, "title")
        progress = progress_for(context)
        progress("generating", {"label": "生成大纲"})
        frame = with_provider(lambda: workbench._framework(
            title, str(args.get("persona") or "深度观察者"),
            str(args.get("requirements") or "")))
        outline = "\n".join(f"{index}. {part}" for index, part in enumerate(frame["outline"], 1))
        progress("generated", {"label": "大纲已生成", "count": len(frame["outline"])})
        return ToolResult({"title": title, "framework": frame}, (
            ArtifactOutput(type="outline", title=title, content=outline,
                           content_json={"framework": frame}),
        ))

    def write_article(args, context):
        title = str(args.get("title") or args.get("topic") or "").strip()
        if not title:
            raise ValueError("title or topic is required")
        persona, requirements = str(args.get("persona") or "深度观察者"), str(args.get("requirements") or "")
        frame = args.get("framework")
        saved_outline = latest_artifact(context, "outline")
        if saved_outline:
            frame = dict((saved_outline.get("content_json") or {}).get("framework") or {})
            edited_lines = [line.strip().split(". ", 1)[-1].strip()
                            for line in (saved_outline.get("content") or "").splitlines()
                            if line.strip()]
            if len(edited_lines) >= 2:
                frame["outline"] = edited_lines
        if not isinstance(frame, dict) or not frame.get("outline"):
            frame = with_provider(lambda: workbench._framework(title, persona, requirements))
        progress = progress_for(context)
        progress("generating", {"label": "生成正文"})
        article = with_provider(lambda: workbench._draft(title, frame, persona, requirements))
        progress("generated", {"label": "正文已生成", "count": len(article)})
        return article_result(title, article)

    def revise_article(args, context):
        article, requirements = required_text(args, "article"), required_text(args, "requirements")
        response = context.model_service.create_response([
            {"role": "system", "content": "你是公众号编辑。严格基于原文执行用户修改要求，保留未要求修改的事实、结构和内容，只输出修改后的完整正文。"},
            {"role": "user", "content": f"修改要求：\n{requirements}\n\n原文：\n{article}"},
        ], timeout=max(60, int(workbench._setting("WECHAT_TEXT_REQUEST_TIMEOUT", "300") or 300)),
           idempotency_key=context.idempotency_key,
           run_id=context.run_id, user_id=context.user_id)
        return article_result(str(args.get("title") or "修订稿"), response.text)

    def review_article(args, context):
        saved_article = latest_artifact(context, "article")
        article = (saved_article or {}).get("content") or required_text(args, "article")
        requirements = str(args.get("requirements") or "").strip()
        session = {
            "id": f"{context.run_id}-review-{uuid.uuid4().hex[:12]}",
            "topic": str(args.get("title") or "公众号文章"),
            "article": article,
            "brief": requirements,
            "conversation": [{"role": "user", "content": requirements}],
            "theme": "default",
            "image_plan": {},
            "images": [],
            "skill_runs": [],
        }
        reviewed, report = with_provider(lambda: workbench._review(article, session))
        progress_for(context)("generated", {"label": "复核完成", "count": len(reviewed)})
        return ToolResult({"title": session["topic"], "article": reviewed, "review": report}, (
            ArtifactOutput(type="article", title=session["topic"], content=reviewed),
            ArtifactOutput(type="report", title="反 AI 复核报告", content_json=report),
        ))

    def typeset_article(args, context):
        artifacts = conversation_repository.list_artifacts(context.conversation_id, context.user_id)
        saved_article = latest_artifact(context, "article", artifacts)
        article = (saved_article or {}).get("content") or required_text(args, "article")
        session = {"id": uuid.uuid4().hex, "topic": str(args.get("title") or "公众号文章"),
                   "article": article,
                   "theme": str(args.get("theme") or "default"), "image_plan": {}, "images": [],
                   "skill_runs": [], "brief": str(args.get("requirements") or ""),
                   "typeset_html": "", "preview_document": ""}
        latest_article = max((item for item in artifacts if item["type"] == "article"
                              and item.get("run_id") != context.run_id),
                             key=lambda item: item["created_at"], default=None)
        image_artifacts = [item for item in artifacts if item["type"] == "image"
                           and item.get("storage_key") and (not latest_article or
                           item["created_at"] >= latest_article["created_at"])]
        image_artifacts.sort(key=lambda item: item["created_at"])
        image_dir = workbench.OUTPUT_DIR / session["id"] / "images"
        for index, item in enumerate(image_artifacts[-8:], 1):
            source = context.storage.local_path(item["storage_key"])
            if source is None:
                raise ValueError("当前存储不支持读取已生成配图，排版未执行")
            image_dir.mkdir(parents=True, exist_ok=True)
            filename = f"image-{index}{source.suffix}"
            shutil.copyfile(source, image_dir / filename)
            caption = str(item.get("title") or "AI 示意图")
            kind = "cover" if "封面" in caption else "body"
            session["images"].append({"kind": kind, "plan_index": index,
                                      "file": filename, "caption": caption})
            session["image_plan"].setdefault("images", []).append(
                {"kind": kind, "caption": caption})
        progress_for(context)("generating", {"label": "生成公众号 HTML"})
        html = with_provider(lambda: workbench._typeset(session))
        preview = session.get("preview_document", "") or html
        progress_for(context)("generated", {"label": "排版已完成", "count": len(preview)})
        return ToolResult({"html": html, "preview_document": preview}, (
            ArtifactOutput(type="html", title="排版结果", content=preview),
        ))

    return {"search_topics": search_topics, "create_outline": create_outline,
            "write_article": write_article,
            "revise_article": revise_article, "review_article": review_article,
            "generate_image": model_image, "typeset_article": typeset_article}
