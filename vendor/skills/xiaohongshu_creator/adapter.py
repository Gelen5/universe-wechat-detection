from server import creator_tools
from server.skills.adapter_support import generate_images, required_text, with_provider
from server.skills.tool_result import ArtifactOutput, ToolResult


def create_tools():
    def draft(args, context):
        values = {"topic": required_text(args, "topic"), "account": str(args.get("account") or ""),
                  "audience": str(args.get("audience") or ""), "goal": str(args.get("goal") or "建立信任"),
                  "evidence": str(args.get("evidence") or ""), "content_type": str(args.get("content_type") or ""),
                  "image_count": int(args.get("image_count", 6)), "requirements": str(args.get("requirements") or "")}
        data = with_provider(lambda: creator_tools.xiaohongshu_package(**values))
        return ToolResult(data, (ArtifactOutput(type="article", title=str(data.get("title") or "小红书草稿"),
                                                         content=str(data.get("content") or data), content_json=data),))
    return {"generate_draft": draft,
            "generate_images": lambda args, context: generate_images(args, context, product="xiaohongshu")}

