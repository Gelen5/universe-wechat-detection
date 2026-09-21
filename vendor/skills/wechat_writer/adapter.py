from __future__ import annotations

import uuid

from server.skills.adapter_support import article_result, model_image, required_text, topics_result, with_provider
from server.skills.tool_result import ArtifactOutput, ToolResult
from server import workbench


def create_tools():
    def search_topics(args, context):
        return topics_result(with_provider(lambda: workbench._suggestions(
            required_text(args, "topic"), str(args.get("persona") or "深度观察者"))))

    def write_article(args, context):
        title = str(args.get("title") or args.get("topic") or "").strip()
        if not title:
            raise ValueError("title or topic is required")
        persona, requirements = str(args.get("persona") or "深度观察者"), str(args.get("requirements") or "")
        frame = args.get("framework")
        if not isinstance(frame, dict) or not frame.get("outline"):
            frame = with_provider(lambda: workbench._framework(title, persona, requirements))
        article = with_provider(lambda: workbench._draft(title, frame, persona, requirements))
        return article_result(title, article)

    def revise_article(args, context):
        article, requirements = required_text(args, "article"), required_text(args, "requirements")
        response = context.model_service.create_response([
            {"role": "system", "content": "你是公众号编辑。严格基于原文执行用户修改要求，保留未要求修改的事实、结构和内容，只输出修改后的完整正文。"},
            {"role": "user", "content": f"修改要求：\n{requirements}\n\n原文：\n{article}"},
        ], timeout=180, idempotency_key=context.idempotency_key,
           run_id=context.run_id, user_id=context.user_id)
        return article_result(str(args.get("title") or "修订稿"), response.text)

    def typeset_article(args, context):
        article = required_text(args, "article")
        session = {"id": uuid.uuid4().hex, "article": article,
                   "theme": str(args.get("theme") or "default"), "image_plan": {}, "images": [],
                   "skill_runs": [], "brief": str(args.get("requirements") or ""),
                   "typeset_html": "", "preview_document": ""}
        html = with_provider(lambda: workbench._typeset(session))
        preview = session.get("preview_document", "") or html
        return ToolResult({"html": html, "preview_document": preview}, (
            ArtifactOutput(type="html", title="排版结果", content=preview),
        ))

    return {"search_topics": search_topics, "write_article": write_article,
            "revise_article": revise_article, "generate_image": model_image,
            "typeset_article": typeset_article}

