import os, unittest
from unittest.mock import patch
from server import skill_host

class ModelRoutingTests(unittest.TestCase):
    def test_draft_and_review_use_prose_model(self):
        with patch.dict(os.environ, {"WECHAT_DRAFT_MODEL": "claude-sonnet-5",
                                     "WECHAT_REVIEW_MODEL": "claude-sonnet-5",
                                     "WECHAT_STRUCTURE_MODEL": "claude-haiku-5-5"}):
            self.assertEqual("claude-sonnet-5", skill_host.model_for("draft"))
            self.assertEqual("claude-sonnet-5", skill_host.model_for("review"))
            self.assertEqual("claude-haiku-5-5", skill_host.model_for("strategy"))
            self.assertEqual("claude-haiku-5-5", skill_host.model_for("topic"))

    def test_unset_env_falls_back_to_configured_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual("", skill_host.model_for("draft"))

    def test_one_click_writing_has_its_own_model_switch(self):
        """一键成文可以单独换模型，不影响诊断/贴图/图片 prompt 这些结构化任务。"""
        from server import qihaoshou
        with patch.dict(os.environ, {"WECHAT_QIAHAOSHOU_MODEL": "claude-sonnet-5",
                                     "WECHAT_TEXT_MODEL": "gpt-6.1-sol"}, clear=True):
            self.assertEqual("claude-sonnet-5", qihaoshou.writing_model())
        # 没配专属开关时回落到全局默认，行为与改动前一致
        with patch.dict(os.environ, {"WECHAT_TEXT_MODEL": "gpt-6.1-sol"}, clear=True):
            self.assertEqual("gpt-6.1-sol", qihaoshou.writing_model())

if __name__ == "__main__":
    unittest.main()
