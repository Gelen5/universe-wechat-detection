import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import creator_tools, image_provider


class CreatorToolsTests(unittest.TestCase):
    def test_xiaohongshu_package_uses_six_card_contract(self):
        payload = {
            "stage": "starter",
            "titles": [{"text": "标题", "keyword": "关键词", "reason": "具体", "promise": "步骤"}] * 3,
            "selected_title": "具体标题",
            "body": "第一步，完成一件具体事情。" * 20,
            "cards": [
                {"index": index, "role": "cover" if index == 1 else "step", "headline": f"第{index}页", "message": "一个重点", "action": "不同动作", "visual_prompt": "明亮工作台"}
                for index in range(1, 7)
            ],
            "precheck": {"status": "ready", "issues": []},
        }
        with patch.object(creator_tools.workbench, "_json_text", return_value=payload):
            result = creator_tools.xiaohongshu_package("主题", "账号", "读者", "教育", "", "流程拆解型")
        self.assertEqual(len(result["cards"]), 6)
        self.assertEqual(result["evidence_state"], "unknown")
        self.assertEqual(result["skill"], "xiaohongshu-creator-skill")

    def test_tie_tu_plan_preserves_count_and_contract(self):
        enriched = {
            "angle": "从生活场景切入",
            "copy": "配套文案",
            "cta": "收藏后慢慢看",
            "cards": [
                {"index": index, "overlay_text": f"卡片{index}", "caption": "短句", "visual_subject": "主体", "composition": "3:4", "scene": f"场景{index}", "action": f"动作{index}"}
                for index in range(1, 5)
            ],
        }
        with patch.object(creator_tools.workbench, "_json_text", return_value=enriched):
            result = creator_tools.tie_tu_plan("生活方式", "慢旅行", "旅行换一种玩法", "list", 4, "温暖", "40+", "off")
        self.assertEqual(result["image_count"], 4)
        self.assertEqual(len(result["cards"]), 4)
        self.assertEqual(result["cards"][1]["card_brief"]["action"], "动作2")

    def test_image_generation_saves_api_result(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(creator_tools, "OUTPUT_DIR", Path(folder)), patch.object(
                image_provider,
                "generate",
                return_value={"data": [{"b64_json": base64.b64encode(png).decode("ascii")}]},
            ):
                result = creator_tools.generate_card_image("tie-tu", "session123", {"index": 1, "overlay_text": "早安"}, "温暖")
            self.assertGreater(result["bytes"], 0)
            self.assertIn("/api/creator-tools/assets/tie-tu/session123/card-01.png", result["url"])

    def test_hit_detector_returns_editorial_gate(self):
        body = "退休以后，先记录真实开支，再和家人确认生活计划。\n\n" * 30
        result = creator_tools.detect_article("退休以后，先做这三件事", body)
        self.assertIn(result["editorial_gate"]["label"], {"暂缓发布", "修改后复核", "可进入人工终审"})
        self.assertIn("scores", result)
        self.assertEqual(result["skill"], "wechat-hit-detector-skill")


if __name__ == "__main__":
    unittest.main()
