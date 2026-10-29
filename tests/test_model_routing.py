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

if __name__ == "__main__":
    unittest.main()
