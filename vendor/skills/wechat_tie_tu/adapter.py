from server import creator_tools
from server.skills.adapter_support import generate_images, required_text, with_provider
from server.skills.tool_result import ArtifactOutput, ToolResult


def create_tools():
    def draft(args, context):
        values = {"industry": str(args.get("industry") or ""), "topic": required_text(args, "topic"),
                  "title": str(args.get("title") or ""), "content_type": args.get("content_type"),
                  "image_count": int(args.get("image_count", 4)), "style": str(args.get("style") or ""),
                  "audience": str(args.get("audience") or ""), "portrait_mode": str(args.get("portrait_mode") or ""),
                  "requirements": str(args.get("requirements") or "")}
        data = with_provider(lambda: creator_tools.tie_tu_plan(**values))
        return ToolResult(data, (ArtifactOutput(type="article", title=str(data.get("title") or "贴图号草稿"),
                                                         content=str(data.get("content") or data), content_json=data),))
    return {"generate_draft": draft,
            "generate_images": lambda args, context: generate_images(args, context, product="tie-tu")}

