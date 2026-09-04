import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import workbench


class WorkbenchTypesetTests(unittest.TestCase):
    def test_public_session_view_removes_all_model_metadata(self):
        session = {
            "id": "public-session",
            "provider": {
                "text": {"configured": True, "model": "private-text-model"},
                "image": {"configured": True, "model": "private-image-model"},
            },
            "images": [{"url": "/image.png", "model": "private-image-model"}],
            "review": {"audit": {"text_model": "private-text-model"}},
        }

        view = workbench._session_view(session)

        self.assertEqual(view["provider"]["text"], {"configured": True})
        self.assertEqual(view["images"], [{"url": "/image.png"}])
        self.assertEqual(view["review"], {"audit": {}})

    def test_provider_status_does_not_expose_configured_model(self):
        with patch.object(workbench, "_setting", side_effect=lambda name, default="": {
            "WECHAT_TEXT_API_KEY": "text-key",
            "WECHAT_IMAGE_API_KEY": "image-key",
            "WECHAT_TEXT_MODEL": "private-text-model",
            "WECHAT_IMAGE_MODEL": "private-image-model",
        }.get(name, default)):
            status = workbench.provider_status()

        self.assertEqual(status["text"], {"configured": True})
        self.assertEqual(status["image"], {"configured": True})

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

    def test_article_markdown_places_body_image_before_first_section(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_output = workbench.OUTPUT_DIR
            workbench.OUTPUT_DIR = Path(temp_dir)
            try:
                session_id = "image-placement"
                image_dir = workbench.OUTPUT_DIR / session_id / "images"
                image_dir.mkdir(parents=True)
                (image_dir / "cover.jpg").write_bytes(b"cover")
                (image_dir / "body.jpg").write_bytes(b"body")
                markdown = workbench._build_article_markdown({
                    "id": session_id, "topic": "标题", "theme": "default",
                    "article": "导语第一段。\n\n导语第二段。\n\n## 第一节\n\n正文。",
                    "images": [{"kind": "cover", "file": "cover.jpg"}, {"kind": "body", "file": "body.jpg"}],
                })
                body_position = markdown.rfind("![正文配图]")
                self.assertGreater(body_position, markdown.find("导语第二段"))
                self.assertLess(body_position, markdown.find("## 第一节"))
            finally:
                workbench.OUTPUT_DIR = old_output


if __name__ == "__main__":
    unittest.main()
