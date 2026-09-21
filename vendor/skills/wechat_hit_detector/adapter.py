from server import creator_tools
from server.skills.adapter_support import report_result, required_text, with_provider


def create_tools():
    def review(args, context):
        result = creator_tools.detect_article(str(args.get("title") or ""), required_text(args, "body"), str(args.get("track") or "auto"))
        return report_result("发布前复核", result)

    def rewrite(args, context):
        title, body = str(args.get("title") or ""), required_text(args, "body")
        detected = args.get("detector_result") if isinstance(args.get("detector_result"), dict) else creator_tools.detect_article(title, body)
        result = with_provider(lambda: creator_tools.rewrite_article(title, body, detected))
        return report_result("复核修改稿", result)
    return {"review_article": review, "rewrite_article": rewrite}

