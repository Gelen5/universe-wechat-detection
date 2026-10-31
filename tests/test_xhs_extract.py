"""Helpers and the extraction contract, offline (no upstream calls)."""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from tests import support  # noqa: F401 - isolated account database
from fastapi.testclient import TestClient

from server import xhs_extract
from server.main import app

ROOT = Path(__file__).resolve().parents[1]


def fake_state_html(note: dict, extra_note: dict | None = None) -> str:
    detail = {"lastNoteId": {"note": note}}
    if extra_note is not None:
        detail["older"] = {"note": extra_note}
    state = {"note": {"noteDetailMap": detail, "currentNoteId": note.get("noteId", "")}}
    return ("<html><body><script>window.__INITIAL_STATE__="
            + json.dumps(state, ensure_ascii=False) + "</script></body></html>")


VIDEO_NOTE = {
    "noteId": "6aa75cdc000000000b0036e7",
    "type": "video",
    "title": "带郑恺哥勇闯Hyrox北京站",
    "desc": "今天试了一下\x08hyrox",
    "time": 1786666053000,
    "lastUpdateTime": 1786666053000,
    "user": {"nickname": "测试作者", "userId": "abc123"},
    "interactInfo": {"likedCount": "1.2万", "collectedCount": "284", "commentCount": "392", "shareCount": "53"},
    "tagList": [{"name": "健身"}, {"name": "Hyrox"}],
    "imageList": [{"urlDefault": "http://sns-webpic-qc.xhscdn.com/a/cover.jpg", "width": 1080, "height": 1440}],
    "video": {"media": {"video": {"duration": 26}, "stream": {"h264": [
        {"masterUrl": "http://sns-video-v6.xhscdn.com/stream/sd.mp4", "size": 1000, "width": 720, "qualityType": "SD"},
        {"masterUrl": "http://sns-video-v6.xhscdn.com/stream/hd.mp4", "size": 9000, "width": 1080, "qualityType": "HD"},
    ]}}},
}

IMAGE_NOTE = {
    "noteId": "111122223333444455556666",
    "type": "normal",
    "title": "图文作品",
    "desc": "三张图",
    "user": {"nickname": "图文作者", "userId": "u2"},
    "interactInfo": {"likedCount": "10+", "collectedCount": "", "commentCount": "-", "shareCount": "0"},
    "tagList": [{"name": "记录"}],
    "imageList": [
        {"urlDefault": "http://sns-webpic-qc.xhscdn.com/1.jpg", "width": 1080, "height": 1440, "livePhoto": True},
        {"url": "http://sns-webpic-qc.xhscdn.com/2.jpg", "width": 1080, "height": 1440},
        {"infoList": [{"imageScene": "WB_PRV", "url": "http://sns-webpic-qc.xhscdn.com/3p.jpg"},
                      {"imageScene": "WB_DFT", "url": "http://sns-webpic-qc.xhscdn.com/3.jpg"}]},
    ],
}


class HelperTests(unittest.TestCase):
    def test_counts_convert_human_written_numbers(self):
        cases = {"1.2万": 12000, "5840": 5840, "10+": 10, "2.3w": 23000, "1亿": 100_000_000,
                 "999": 999, "": -1, "-": -1, "无": -1, 12: 12, True: -1}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(expected, xhs_extract.to_count(raw))

    def test_links_normalize_from_share_text_and_short_ids(self):
        para = "看看这个 https://www.xiaohongshu.com/explore/6aa75cdc000000000b0036e7?xsec_token=AB12 太好笑了"
        self.assertIn("xsec_token=AB12", xhs_extract.normalize_link(para))
        share = "https://www.xiaohongshu.com/discovery/item/6aa75cdc000000000b0036e7?xsec_token=x&xsec_source=app_share"
        self.assertTrue(xhs_extract.normalize_link(share).endswith("xsec_source=app_share"))
        self.assertEqual("https://www.xiaohongshu.com/explore/6aa75cdc000000000b0036e7",
                         xhs_extract.normalize_link("6aa75cdc000000000b0036e7"))

    def test_unrelated_text_is_rejected_with_actionable_message(self):
        with self.assertRaises(xhs_extract.HTTPException) as caught:
            xhs_extract.normalize_link("今天天气不错")
        self.assertEqual(400, caught.exception.status_code)
        self.assertIn("链接", caught.exception.detail)


class ExtractContractTests(unittest.TestCase):
    def test_video_note_keeps_best_stream_and_strips_control_characters(self):
        with mock.patch.object(xhs_extract.requests, "get") as get:
            get.return_value = mock.Mock(status_code=200, text=fake_state_html(VIDEO_NOTE))
            note = xhs_extract.fetch_note("https://www.xiaohongshu.com/explore/6aa75cdc000000000b0036e7?xsec_token=t")
        self.assertEqual("video", note["kind"])
        self.assertEqual("hd.mp4", note["video"]["url"].rsplit("/", 1)[-1])
        self.assertEqual(26, note["video"]["duration"])
        self.assertEqual(12000, note["stats"]["liked"])
        self.assertNotIn("\x08", note["desc"])
        self.assertEqual(["健身", "Hyrox"], note["tags"])
        self.assertEqual("2026-08-14 08:07", note["published"])
        # 视频的 imageList 只是封面帧，不能报成「N 张配图」。
        self.assertEqual(0, note["imageCount"])
        self.assertIsNotNone(note["cover"])
        self.assertTrue(note["cover"]["url"].startswith("https://"))

    def test_image_note_reads_all_images_and_falls_back_to_dft_scene(self):
        note = xhs_extract.build_note(IMAGE_NOTE, "https://www.xiaohongshu.com/explore/111122223333444455556666")
        self.assertEqual("image", note["kind"])
        self.assertEqual(3, note["imageCount"])
        self.assertTrue(note["images"][2]["url"].endswith("3.jpg"))
        self.assertTrue(note["images"][0]["live"])
        self.assertEqual(10, note["stats"]["liked"])
        self.assertEqual(-1, note["stats"]["collected"])
        self.assertIsNone(note["video"])

    def test_tokenless_page_reports_the_real_reason(self):
        """A bare /explore/<id> returns an empty shell; say so instead of 'failed'."""
        with mock.patch.object(xhs_extract.requests, "get") as get:
            get.return_value = mock.Mock(status_code=200, text="<html>no state here</html>")
            with self.assertRaises(xhs_extract.HTTPException) as caught:
                xhs_extract.fetch_note("https://www.xiaohongshu.com/explore/6aa75cdc000000000b0036e7")
        self.assertEqual(422, caught.exception.status_code)
        self.assertIn("xsec_token", caught.exception.detail)

    def test_upstream_failures_map_to_gateway_errors(self):
        with mock.patch.object(xhs_extract.requests, "get") as get:
            get.side_effect = xhs_extract.requests.Timeout()
            with self.assertRaises(xhs_extract.HTTPException) as caught:
                xhs_extract.fetch_note("https://www.xiaohongshu.com/explore/x")
            self.assertEqual(504, caught.exception.status_code)
            get.side_effect = None
            get.return_value = mock.Mock(status_code=500, text="")
            with self.assertRaises(xhs_extract.HTTPException) as caught:
                xhs_extract.fetch_note("https://www.xiaohongshu.com/explore/x")
            self.assertEqual(502, caught.exception.status_code)


class MediaProxyTests(unittest.TestCase):
    def test_proxy_refuses_hosts_that_are_not_xiaohongshu(self):
        with TestClient(app) as client:
            login = client.post('/api/auth/login', json={'email': 'admin@example.com',
                                                        'password': 'testing-pass-123'})
            self.assertEqual(200, login.status_code)
            for url in ('https://example.com/a.jpg', 'file:///etc/passwd',
                        'https://xiaohongshu.com.evil.test/a.jpg'):
                with self.subTest(url=url):
                    self.assertEqual(400, client.get('/api/xhs/media', params={'url': url}).status_code)

    def test_proxy_rejects_non_media_content_types(self):
        with mock.patch.object(xhs_extract.requests, 'get') as get:
            get.return_value = mock.Mock(status_code=200, headers={'content-type': 'text/html'},
                                         iter_content=lambda *a, **k: iter([b'<html>']), close=lambda: None)
            with self.assertRaises(xhs_extract.HTTPException) as caught:
                xhs_extract.api_media('https://sns-webpic-qc.xhscdn.com/x')
            self.assertEqual(415, caught.exception.status_code)


class RouteRegistrationTests(unittest.TestCase):
    def test_endpoints_require_login_and_are_not_public(self):
        with TestClient(app) as client:
            self.assertEqual(401, client.post('/api/xhs/extract', json={'url': 'x'}).status_code)

    def test_extraction_is_free_but_rate_limited_by_the_paid_gate(self):
        """Extraction calls no model, so it must not appear in the point table."""
        from server.accounts import DEFAULT_PRICING
        paths = {path for _method, path, *_rest in DEFAULT_PRICING}
        self.assertNotIn('/api/xhs/extract', paths)
        self.assertNotIn('/api/xhs/media', paths)


if __name__ == '__main__':
    unittest.main()
