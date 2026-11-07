"""抖音提取：链接被拒时要说清「粘的是什么」，并且必须留下日志。

这一段是给运维和用户同时用的：

* 用户侧 —— 粘了抖音主页 / 直播间 / 小红书链接时，提示要直接点名是哪一种，
  否则「没有识别到抖音作品链接」会让人以为是复制错了。
* 运维侧 —— 被拒的请求必须能查到。原来这里用的是裸 ``logging.getLogger``，
  web 容器里没有 handler、effective level 是 WARNING，``logger.info`` 全部
  静默丢弃，线上只剩一个 400 状态码，看不出用户到底粘了什么。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import douyin_extract  # noqa: E402


def _detail(raw: str) -> str:
    with pytest.raises(Exception) as error:
        douyin_extract.normalize_link(raw)
    assert getattr(error.value, "status_code", None) == 400
    return error.value.detail


class TestAccepted:
    @pytest.mark.parametrize("raw", [
        "https://www.douyin.com/video/7699784646996823306",
        "https://www.douyin.com/note/7699784646996823306",
        "https://www.iesdouyin.com/share/video/7699784646996823306/?region=CN",
        "https://www.douyin.com/discover?modal_id=7699784646996823306",
        "7699784646996823306",
        "3.21 复制打开抖音，看看作品 https://www.douyin.com/video/7699784646996823306",
    ])
    def test_still_reads_a_real_work_link(self, raw):
        aweme_id, link = douyin_extract.normalize_link(raw)
        assert aweme_id == "7699784646996823306"
        assert link == "https://www.douyin.com/video/7699784646996823306"


class TestRejectMessages:
    def test_empty_input_asks_for_a_link(self):
        assert _detail("") == "请先粘贴抖音作品链接"
        assert _detail("   ") == "请先粘贴抖音作品链接"

    @pytest.mark.parametrize("raw,expected", [
        ("https://www.douyin.com/user/MS4wLjABAAAAxxxx", "抖音主页链接"),
        ("https://www.iesdouyin.com/share/user/MS4wLjABAAAA", "抖音主页链接"),
        ("https://live.douyin.com/123456789", "抖音直播间链接"),
        ("https://www.douyin.com/search/%E7%BE%8E%E9%A3%9F", "抖音搜索页链接"),
        ("https://www.douyin.com/collection/123456", "抖音合集链接"),
        ("https://www.douyin.com/hashtag/123456", "抖音话题页链接"),
    ])
    def test_names_the_douyin_page_instead_of_a_generic_refusal(self, raw, expected):
        detail = _detail(raw)
        assert expected in detail
        # 每一种都要给出下一步动作，不能只说「错了」。
        assert "分享" in detail and "复制链接" in detail

    @pytest.mark.parametrize("raw,expected", [
        ("https://www.xiaohongshu.com/explore/6912ab34cd00ef0001a2b3c4", "小红书"),
        ("https://xhslink.com/a/abc123", "小红书"),
        ("https://www.kuaishou.com/short-video/3xabc", "快手"),
        ("https://weibo.com/1234567890/abcdef", "微博"),
        ("https://www.bilibili.com/video/BV1xx411c7mD", "B站"),
        ("https://p3-pc-sign.douyinpic.com/aweme/a.jpeg?x-expires=1", "图片地址"),
    ])
    def test_points_at_the_platform_that_owns_the_link(self, raw, expected):
        assert expected in _detail(raw)

    def test_xiaohongshu_learns_where_to_go_instead(self):
        assert "小红书提取" in _detail("https://www.xiaohongshu.com/explore/abc123")

    def test_short_link_failure_tells_the_user_to_copy_from_the_browser(self):
        original = douyin_extract._resolve_short_link
        douyin_extract._resolve_short_link = lambda link: None
        try:
            detail = _detail("5.23 复制打开抖音 https://v.douyin.com/iRNBho6u/")
        finally:
            douyin_extract._resolve_short_link = original
        assert "短链" in detail and "浏览器" in detail

    def test_pure_text_gets_the_share_path(self):
        detail = _detail("5.23 复制打开抖音，看看【某某】的作品")
        assert "没有识别到链接" in detail
        assert "分享" in detail and "复制链接" in detail


class TestRejectLogging:
    def _capture(self, raw: str) -> dict:
        calls: list[dict] = []
        original = douyin_extract.event
        douyin_extract.event = lambda name, **fields: calls.append({"event": name, **fields})
        try:
            _detail(raw)
        finally:
            douyin_extract.event = original
        assert len(calls) == 1, calls
        return calls[0]

    def test_rejection_is_logged_with_reason_and_shape(self):
        call = self._capture("https://www.douyin.com/user/MS4wLjABAAAAxxxx")
        assert call["event"] == "douyin.link_rejected"
        assert call["reason"] == "douyin_page"
        assert call["host"] == "www.douyin.com"
        assert call["path"] == "/user/MS4wLjABAAAAxxxx"

    def test_log_never_carries_the_raw_text(self):
        # 抖音链接的 query 里带签名和过期时间，整串落日志既不有用也不安全。
        raw = "https://www.douyin.com/search/x?a_bogus=SECRETSIGN&x-expires=1796612400"
        call = self._capture(raw)
        blob = repr(call)
        assert "SECRETSIGN" not in blob
        assert "a_bogus" not in blob
        assert call["path"] == "/search/x"

    def test_platform_rejections_are_logged_as_foreign(self):
        call = self._capture("https://www.xiaohongshu.com/explore/abc123")
        assert call["reason"] == "foreign"
        assert call["host"] == "www.xiaohongshu.com"

    def test_empty_input_is_logged_without_a_host(self):
        call = self._capture("")
        assert call["reason"] == "empty"
        assert call["host"] is None


class TestLoggerWiring:
    def test_uses_the_shared_observability_logger(self):
        # 裸 getLogger 在 web 容器里 info 会被丢掉，这一条就是那次事故的护栏。
        assert douyin_extract.logger.name == "universe"
        assert douyin_extract.logger.handlers, "抖音模块的日志必须真的有 handler"
        assert douyin_extract.logger.getEffectiveLevel() <= 20

    def test_success_path_emits_a_structured_event(self):
        calls: list[dict] = []
        original_event = douyin_extract.event
        original_request = douyin_extract._signed_request
        douyin_extract.event = lambda name, **fields: calls.append({"event": name, **fields})
        douyin_extract._signed_request = lambda aweme_id: {
            "aweme_id": aweme_id, "desc": "测试作品", "create_time": 1792745760,
            "aweme_type": 0, "author": {"nickname": "作者"},
            "statistics": {"digg_count": 1}, "images": None, "video": None,
        }
        try:
            douyin_extract.api_extract(douyin_extract.ExtractRequest(
                url="https://www.douyin.com/video/7699784646996823306"))
        finally:
            douyin_extract.event = original_event
            douyin_extract._signed_request = original_request
        assert [call["event"] for call in calls] == ["douyin.extract_ok"]
        assert calls[0]["id"] == "7699784646996823306"
        assert isinstance(calls[0]["elapsed_ms"], int)


class TestFrontendGuide:
    def test_error_box_offers_the_share_path_and_long_messages_stay_up(self):
        js = (ROOT / "static" / "douyin-extract.js").read_text(encoding="utf-8")
        css = (ROOT / "static" / "douyin-extract.css").read_text(encoding="utf-8")
        index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        assert "error.status === 400" in js
        assert "dy-error-hint" in js
        assert ".dy-error-hint" in css
        # 引导句比「已复制」长得多，固定 2.6 秒读不完。
        assert "text.length * 200" in js
        assert "douyin-extract.js?v=20261107-link-guide" in index
        assert "douyin-extract.css?v=20261107-link-guide" in index
