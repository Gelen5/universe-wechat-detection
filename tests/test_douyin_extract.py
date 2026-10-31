"""Douyin extraction: link normalization, payload parsing, media safety.

These run offline. The live path (signing + a real作品) is exercised by
``tests/douyin_live_check.py``, which needs a real ``DOUYIN_COOKIE``; the
tests here pin the parts that must not drift silently: which links are
accepted, how a payload becomes a note, and which hosts the media proxy will
forward to.

The payloads are trimmed copies of real responses: field names, nesting and the
``-1`` sentinel Douyin uses for "hidden from visitors" are kept exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import douyin_extract  # noqa: E402


VIDEO_DETAIL = {
    "aweme_id": "7699784646996823306",
    "desc": "100w机会！21.5万粉丝的海外AI博主 #AI应用 #品牌出海",
    "create_time": 1792745760,
    "aweme_type": 0,
    "author": {
        "nickname": "阿杭 在赚钱",
        "unique_id": "",
        "short_id": "12345678",
        "sec_uid": "MS4wLjABAAAArYIb9WtHexample",
        "avatar_thumb": {"url_list": ["https://p3-sign.douyinpic.com/aweme/100x100/a.jpeg?x-expires=1"]},
    },
    "statistics": {
        "digg_count": 3963, "comment_count": 74, "share_count": 1022,
        "collect_count": 3321, "play_count": -1,
    },
    "text_extra": [{"hashtag_name": "AI应用"}, {"hashtag_name": "品牌出海"}],
    "images": None,
    "video": {
        "width": 1706,
        "height": 1080,
        "duration": 297920,
        "cover": {"url_list": ["https://p3-sign.douyinpic.com/obj/cover.jpeg?x-expires=1"]},
        "play_addr": {"url_list": ["http://v26-web.douyinvod.com/low.mp4?x-expires=1"]},
        "bit_rate": [
            {"bit_rate": 895200, "play_addr": {"url_list": ["http://v11-weba.douyinvod.com/best.mp4?x-expires=1"]}},
            {"bit_rate": 788715, "play_addr": {"url_list": ["http://v11-weba.douyinvod.com/worse.mp4?x-expires=1"]}},
        ],
    },
}

GALLERY_DETAIL = {
    "aweme_id": "7500000000000000000",
    "desc": "九张图讲完一套流程 #干货",
    "create_time": 1792745760,
    "aweme_type": 68,
    "author": {"nickname": "图文作者", "sec_uid": "MS4wLjABAAAAgallery", "avatar_thumb": {"url_list": []}},
    "statistics": {"digg_count": 10, "comment_count": 2, "share_count": 1, "collect_count": 3},
    "text_extra": [{"hashtag_name": "干货"}],
    "images": [
        {"width": 1080, "height": 1440,
         "url_list": ["https://p3-sign.douyinpic.com/obj/1.jpeg?x-expires=1",
                      "https://p9-sign.douyinpic.com/obj/1.jpeg?x-expires=1"]},
        {"width": 1080, "height": 1440, "url_list": ["https://p3-sign.douyinpic.com/obj/2.jpeg?x-expires=1"]},
    ],
    # 真实图文作品（aweme 7360323126909095219，2026-10-31 抓取）里也带一个
    # video：把图片烧成幻灯片的合成视频。字段形状和视频作品一样，所以这里必须
    # 照抄，否则解析器的「图文」分支等于没被测到。
    "video": {
        "width": 1272,
        "height": 1568,
        "duration": 15000,
        "cover": {"url_list": ["https://p3-sign.douyinpic.com/obj/slides-cover.jpeg?x-expires=1"]},
        "play_addr": {"url_list": ["https://v26-web.douyinvod.com/slides.mp4?x-expires=1"]},
    },
}


class TestNormalizeLink:
    @pytest.mark.parametrize("raw", [
        "https://www.douyin.com/video/7699784646996823306",
        "https://www.douyin.com/note/7699784646996823306",
        "https://m.douyin.com/share/video/7699784646996823306",
        "https://www.douyin.com/video/7699784646996823306?previous_page=app_code_link",
        "7699784646996823306",
        "8.43 复制打开抖音，看看【阿杭的作品】 https://www.douyin.com/video/7699784646996823306 长按复制",
    ])
    def test_accepts_every_shape_a_user_pastes(self, raw):
        aweme_id, link = douyin_extract.normalize_link(raw)
        assert aweme_id == "7699784646996823306"
        assert link == "https://www.douyin.com/video/7699784646996823306"

    @pytest.mark.parametrize("raw", [
        "",
        "   ",
        "随便一段话，没有链接",
        "https://www.xiaohongshu.com/explore/abc123",
        "https://www.douyin.com/user/MS4wLjABAAAAxxxx",
    ])
    def test_rejects_what_it_cannot_use(self, raw):
        with pytest.raises(Exception) as error:
            douyin_extract.normalize_link(raw)
        assert getattr(error.value, "status_code", None) == 400


class TestBuildNoteVideo:
    def test_video_note_carries_the_copy_and_the_stats(self):
        note = douyin_extract.build_note(
            VIDEO_DETAIL, "7699784646996823306", "https://www.douyin.com/video/7699784646996823306"
        )
        assert note["kind"] == "video"
        assert note["title"] == "100w机会！21.5万粉丝的海外AI博主 #AI应用 #品牌出海"
        assert note["tags"] == ["#AI应用", "#品牌出海"]
        assert note["author"]["name"] == "阿杭 在赚钱"
        assert note["author"]["sec_uid"] == "MS4wLjABAAAArYIb9WtHexample"
        assert note["stats"]["liked"] == 3963
        # Douyin sends -1 for play counts a visitor may not see; it must not
        # become "0 plays" on the card.
        assert note["stats"]["play"] == -1
        assert note["published"] == "2026-10-23 16:56"

    def test_picks_the_highest_bitrate_and_https(self):
        note = douyin_extract.build_note(VIDEO_DETAIL, "7699784646996823306", "x")
        video = note["video"]
        assert video["url"] == "https://v11-weba.douyinvod.com/best.mp4?x-expires=1"
        assert video["quality"] == "895kbps"
        assert video["duration"] == 297920
        assert video["poster"].startswith("https://p3-sign.douyinpic.com/")


class TestBuildNoteGallery:
    def test_gallery_note_lists_every_image_with_its_size(self):
        note = douyin_extract.build_note(
            GALLERY_DETAIL, "7500000000000000000", "https://www.douyin.com/video/7500000000000000000"
        )
        assert note["kind"] == "image"
        assert note["imageCount"] == 2
        assert [image["url"] for image in note["images"]] == [
            "https://p3-sign.douyinpic.com/obj/1.jpeg?x-expires=1",
            "https://p3-sign.douyinpic.com/obj/2.jpeg?x-expires=1",
        ]
        assert note["images"][0]["width"] == 1080
        # 图片下面不该再出现一台播放器：图文详情里那个 video 是幻灯片合成的，
        # 不是用户要的素材（线上就因此多出一块黑框）。
        assert note["video"] is None
        assert note["cover"] is None
        assert note["duration"] is None

    def test_gallery_note_links_to_note_not_video(self):
        note = douyin_extract.build_note(
            GALLERY_DETAIL, "7500000000000000000", "https://v.douyin.com/7u0ARZrDY9k/"
        )
        assert note["link"] == "https://www.douyin.com/note/7500000000000000000"

    def test_missing_images_and_video_yields_neither(self):
        note = douyin_extract.build_note({"desc": "只有文案"}, "7500000000000000000", "x")
        assert note["kind"] == "video"
        assert note["images"] == []
        assert note["video"] is None
        assert note["title"] == "只有文案"


class TestCounts:
    @pytest.mark.parametrize("raw,expected", [
        (1234, 1234),
        ("1.2万", 12000),
        ("3亿", 300_000_000),
        ("1,234", 1234),
        ("10+", 10),
        (-1, -1),
        (None, -1),
        ("—", -1),
    ])
    def test_to_count(self, raw, expected):
        assert douyin_extract.to_count(raw) == expected


class TestMediaKeyAndHosts:
    def test_key_ignores_the_signature_but_not_the_host(self):
        a = douyin_extract.media_key("https://p3-sign.douyinpic.com/obj/1.jpeg?x-expires=1")
        b = douyin_extract.media_key("https://p3-sign.douyinpic.com/obj/1.jpeg?x-expires=999")
        c = douyin_extract.media_key("https://p9-sign.douyinpic.com/obj/1.jpeg?x-expires=1")
        assert a == b, "签名不同不该产生两份缓存"
        assert a != c, "不同图床不能互相覆盖"

    @pytest.mark.parametrize("url,allowed", [
        ("https://p3-sign.douyinpic.com/obj/1.jpeg", True),
        ("https://v11-weba.douyinvod.com/a.mp4", True),
        ("https://p26-sign.douyinpic.com.evil.example/a.jpeg", False),
        ("https://example.com/a.jpeg", False),
        ("file:///etc/passwd", False),
        ("http://127.0.0.1:8000/health", False),
    ])
    def test_media_proxy_only_forwards_douyin_hosts(self, url, allowed):
        assert douyin_extract._host_allowed(url, douyin_extract.MEDIA_HOST_SUFFIXES) is allowed


class TestFrontendGuards:
    def test_players_are_gated_on_kind(self):
        """结果页的两块媒体区必须只看 kind，不再看 payload 里有没有 video。"""
        js = (ROOT / "static" / "douyin-extract.js").read_text(encoding="utf-8")
        assert "if (note.kind !== 'video') return '';" in js, "图文作品会多出一台播放器"
        assert "if (note.kind !== 'image') return '';" in js, "视频作品会多出一个图片墙"


class TestCredentials:
    def test_missing_cookie_is_503_not_an_empty_note(self, monkeypatch):
        monkeypatch.delenv("DOUYIN_COOKIE", raising=False)
        monkeypatch.setenv("DOUYIN_COOKIE_FILE", "")
        with pytest.raises(Exception) as error:
            douyin_extract._signed_request("7699784646996823306")
        assert getattr(error.value, "status_code", None) == 503
        # 报错必须说清楚是配置问题，而不是「这条作品没内容」。
        assert "DOUYIN_COOKIE" in str(getattr(error.value, "detail", ""))

    def test_cookie_can_arrive_as_the_skills_json(self, monkeypatch):
        monkeypatch.setenv("DOUYIN_COOKIE", '{"cookie": "UIFID=abc; ttwid=def"}')
        assert douyin_extract._cookie() == "UIFID=abc; ttwid=def"

    def test_cookie_jar_parses_a_raw_header(self):
        jar = douyin_extract._cookie_jar("UIFID=abc; ttwid=def; empty=")
        assert jar == {"UIFID": "abc", "ttwid": "def", "empty": ""}
