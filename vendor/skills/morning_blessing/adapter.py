from server import creator_tools
from server.skills.adapter_support import generate_images, with_provider
from server.skills.tool_result import ArtifactOutput, ToolResult


def create_tools():
    def draft(args, context):
        values = {"topic": str(args.get("topic") or "早安祝福"), "image_count": int(args.get("image_count", 4)),
                  "copy_count": int(args.get("copy_count", 3)), "style": str(args.get("style") or ""),
                  "mode": str(args.get("mode") or "article"), "columns": int(args.get("columns", 1)),
                  "image_at": int(args.get("image_at", 1)), "image_position": str(args.get("image_position") or "after"),
                  "size": str(args.get("size") or "768x1024"), "requirements": str(args.get("requirements") or "")}
        data = with_provider(lambda: creator_tools.morning_draft(**values))
        return ToolResult(data, (ArtifactOutput(type="article", title=str(data.get("title") or "早安祝福"),
                                                         content=str(data.get("content") or data), content_json=data),))

    def layout(args, context):
        data = {"changed": args, "text_preserved": True, "images_preserved": True}
        return ToolResult(data, (ArtifactOutput(type="html", title="早安祝福排版",
                                                content=str(args.get("content") or ""), content_json=data),))
    return {"generate_draft": draft,
            "generate_images": lambda args, context: generate_images(args, context, product="tie-tu"),
            "change_layout": layout}

