import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import workbench


class WorkbenchTypesetTests(unittest.TestCase):
    def test_persisted_session_wins_over_stale_process_cache_and_recovers_images(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_output = workbench.OUTPUT_DIR
            workbench.OUTPUT_DIR = Path(temp_dir)
            try:
                session_id = "cross-process-session"
                image_dir = workbench.OUTPUT_DIR / session_id / "images"
                image_dir.mkdir(parents=True)
                (image_dir / "cover-1.jpg").write_bytes(b"cover")
                (image_dir / "body-2.jpg").write_bytes(b"body")
                workbench.SESSIONS[session_id] = {"id": session_id, "user_id": "u1", "images": []}
                persisted = {"id": session_id, "user_id": "u1", "images": [], "article": "newest"}
                with patch.object(workbench.accounts, "load_workbench_session", return_value=persisted):
                    loaded = workbench._get_session(session_id, "u1")
                self.assertEqual(loaded["article"], "newest")
                self.assertEqual([item["kind"] for item in loaded["images"]], ["cover", "body"])
            finally:
                workbench.OUTPUT_DIR = old_output
                workbench.SESSIONS.pop("cross-process-session", None)

    def test_dbs_theme_replaces_old_inline_styles_and_keeps_image(self):
        fragment = '<section style="old"><h1 style="color:blue">标题</h1><p style="old"><img src="data:image/jpeg;base64,AA" style="border-radius:8px"></p></section>'
        themed, style_id = workbench._apply_dbs_wechat_theme(fragment, "default")
        self.assertEqual(style_id, "medium")
        self.assertIn("font-size:28px", themed)
        self.assertIn("data:image/jpeg;base64,AA", themed)
        self.assertIn("border:0;border-radius:0", themed)
        self.assertNotIn("color:blue", themed)


if __name__ == "__main__":
    unittest.main()
