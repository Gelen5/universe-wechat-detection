"""Tie-Tu brief builder without long-form article dependencies."""

from .contracts import ContentBrief, QualityGate


def build_tie_tu_brief(industry: str, topic: str, title: str, content_type: str,
                       audience: str = "", style: str = "") -> ContentBrief:
    return ContentBrief(
        mode="tie_tu",
        intent=f"围绕{topic}制作图片主导的微信贴图号内容",
        audience=audience or "微信读者",
        deliverable="微信贴图号图片组、短文案和手机预览",
        content_type=content_type,
        style=style,
        constraints=["图片与准确中文标题由宿主内置 Image 模型一次生成", "图片来源或生成方式必须可追溯", "发布前通过贴图号质量门禁"],
        quality_gates=[QualityGate("tie_tu", ["card_briefs", "sources", "assets", "mobile_preview"])],
        assumptions=[f"行业：{industry}", f"标题：{title or topic}"],
        metadata={"industry": industry, "topic": topic},
    )
