import pytest
from server import article_visual


def _fake_slot_service(monkeypatch, *frames):
    """回放给定画幅的假图片服务；返回 mock 以便断言请求参数。"""
    import base64
    import io
    from contextlib import nullcontext
    from unittest.mock import MagicMock

    from PIL import Image

    from server import providers

    payloads = []
    for frame in frames:
        buffer = io.BytesIO()
        Image.new('RGB', frame, 'red').save(buffer, format='PNG')
        payloads.append({'data': [{'b64_json': base64.b64encode(buffer.getvalue()).decode()}]})
    service = MagicMock()
    service.generate_image.side_effect = payloads
    monkeypatch.setattr(providers, 'OpenAICompatibleProvider', MagicMock())
    monkeypatch.setattr(providers, 'ModelService', lambda *args, **kwargs: service)
    monkeypatch.setattr(article_visual.workbench, '_setting', lambda *args, **kwargs: 'test')
    monkeypatch.setattr(article_visual.workbench, 'provider_overrides', lambda **kwargs: nullcontext())
    monkeypatch.setattr(article_visual.time, 'sleep', lambda *_: None)
    return service


def test_article_visual_requests_an_explicit_3_4_size(monkeypatch):
    import io

    from PIL import Image

    service = _fake_slot_service(monkeypatch, (1086, 1448))
    result = article_visual.generate_slot_image('测试正文')
    # 原生 3:4 原样返回：不重采样、不补边
    assert Image.open(io.BytesIO(result)).size == (1086, 1448)
    assert service.generate_image.call_count == 1
    assert service.generate_image.call_args.kwargs['size'] == '1024x1365'
    assert '宽高比 3:4' in service.generate_image.call_args.args[0]


def test_article_visual_reframes_a_square_result(monkeypatch):
    import io

    from PIL import Image

    service = _fake_slot_service(monkeypatch, (1024, 1024), (1024, 1024))
    result = article_visual.generate_slot_image('测试正文')
    # 上游两次都回方图：最后一次兜底补成 3:4 画布，而不是把方图发给前端
    assert Image.open(io.BytesIO(result)).size == (1024, 1365)
    assert service.generate_image.call_count == 2
    assert service.generate_image.call_args.kwargs['size'] == '1024x1365'


SAMPLE_HTML = """
<html><head>
<meta property="og:title" content="身家1270亿，中国新晋女首富诞生" />
</head><body>
<h1 id="activity-name">备用标题</h1>
<a id="js_name">象牙财经</a>
<div id="js_content">
  <p>10月27日，胡润研究院发布《2026胡润百富榜》。</p>
  <section><section><p>周群飞本人以1270亿元身家登顶中国女首富。</p></section></section>
  <p><img data-src="https://mmbiz.qpic.cn/a.png" /></p>
  <h2>成长经历</h2>
  <p>1993年，23岁的她开始创业；2003年，正式创立蓝思科技。</p>
</div>
<script>
var ct = "1772250154";
var author = "象牙财经";
</script>
</body></html>
"""


def test_parse_article_html_extracts_meta_and_body():
    article = article_visual.parse_article_html(SAMPLE_HTML, "https://mp.weixin.qq.com/s/demo")

    assert article["title"] == "身家1270亿，中国新晋女首富诞生"
    assert article["account"] == "象牙财经"
    assert article["author"] == "象牙财经"
    assert article["publish_time"].startswith("2026-")
    assert len(article["images"]) == 1
    assert "1270亿元" in article["markdown"]
    assert "## 成长经历" in article["markdown"]


def test_parse_article_html_dedupes_nested_sections():
    article = article_visual.parse_article_html(SAMPLE_HTML)
    assert article["markdown"].count("周群飞本人以1270亿元身家登顶中国女首富。") == 1


def test_normalize_plan_keeps_cover_first_and_limits_body():
    raw = {
        "thesis": "一块玻璃托起女首富",
        "slots": [
            {"id": "b1", "form": "data", "headline": "三个数字", "items": []},
            {"id": "b2", "form": "timeline", "headline": "三十年", "items": []},
            {"id": "b3", "form": "layers", "headline": "拆开手机", "items": []},
            {"id": "b4", "form": "compare", "headline": "前后对比", "items": []},
            {"id": "b5", "form": "clients", "headline": "客户", "items": []},
            {"id": "b6", "form": "unknown", "headline": "丢弃", "items": []},
        ],
    }
    plan = article_visual._normalize_plan(raw, {"title": "标题", "account": "号", "markdown": ""})

    assert plan["slots"][0]["form"] == "cover"
    assert len(plan["slots"]) == 6  # 1 封面 + 最多 5 个正文
    assert [s["order"] for s in plan["slots"]] == [0, 1, 2, 3, 4, 5]
    assert all(s["status"] == "pending" for s in plan["slots"])


def test_normalize_plan_falls_back_when_model_returns_nothing():
    plan = article_visual._normalize_plan(
        {}, {"title": "标题", "account": "号", "markdown": "今年增长了 23.2%，超七成白手起家。"}
    )
    assert plan["slots"][0]["form"] == "cover"
    assert len(plan["slots"]) >= 2


def test_build_image_prompt_carries_exact_text_and_ratio():
    prompt = article_visual.build_image_prompt(
        {
            "form": "data",
            "headline": "一张榜单，三个数字",
            "items": [{"value": "1270亿", "label": "周群飞身家", "note": "第 33 位"}],
        }
    )
    assert "一张榜单，三个数字" in prompt
    assert "1270亿" in prompt
    assert "周群飞身家" in prompt
    assert "3:4" in prompt


def test_cover_prompt_uses_headline_and_kicker():
    prompt = article_visual.build_image_prompt(
        {
            "form": "cover",
            "headline": "1270亿",
            "kicker": "2026 胡润百富榜",
            "items": ["中国女首富", "周群飞"],
            "brief": "一块竖立的手机玻璃盖板",
        }
    )
    assert "1270亿" in prompt
    assert "2026 胡润百富榜" in prompt
    assert "中国女首富" in prompt
    assert "3:4" in prompt


def test_cover_subject_follows_article():
    person = article_visual.build_image_prompt({"form":"cover", "headline":"前AV女优转程序员", "brief":"电脑前的编程场景"}, cover_style="object")
    assert "成年女性" in person
    assert "不声称是当事人真实照片" in person
    assert "桌面上的静物特写" not in person
    product = article_visual.build_image_prompt({"form":"cover", "headline":"一块手机玻璃", "brief":"一块手机玻璃盖板"}, cover_style="object")
    assert "手机玻璃盖板" in product
    assert "成年女性" not in product


def test_parse_invalid_link_gets_actionable_hint():
    import pytest

    with pytest.raises(ValueError) as exc:
        article_visual.parse_article_html("<html><body>参数错误</body></html>")
    assert "重新复制完整链接" in str(exc.value)



def test_plan_model_defaults_to_sonnet_and_can_be_overridden(monkeypatch):
    """配图策划默认走 claude-sonnet-5-5；中转站抽风时可用环境变量切回 Sol。"""
    monkeypatch.delenv("WECHAT_ARTICLE_VISUAL_MODEL", raising=False)
    assert article_visual.plan_model() == "claude-sonnet-5-5"
    monkeypatch.setenv("WECHAT_ARTICLE_VISUAL_MODEL", "gpt-6.1-sol")
    assert article_visual.plan_model() == "gpt-6.1-sol"


def test_plan_evidence_binds_to_current_article_and_rejects_wrong_topic():
    article = {"title":"前演员转行程序员，用 Claude Code 写代码", "markdown":"她退役后开始学习编程，并用 Claude Code 编写程序。"}
    quote = "她退役后开始学习编程，并用 Claude Code 编写程序。"
    raw = {"article_type":"story", "slots":[
        {"id":"cover", "form":"cover", "headline":"转行程序员", "source_quote":"前演员转行程序员，用 Claude Code 写代码"},
        *[{"id":f"body-{i}", "form":"timeline", "headline":"学习编程", "source_quote":quote} for i in range(1,4)]
    ]}
    article_visual.validate_plan(raw, article)
    raw["slots"][1]["source_quote"] = "7ms差距积分发了两次"
    import pytest
    with pytest.raises(ValueError, match="不匹配"):
        article_visual.validate_plan(raw, article)


def test_plan_refuses_unrelated_headline_even_with_real_quote(monkeypatch):
    import pytest
    article = {"title":"学习编程的故事", "markdown":"她退役后开始学习编程，并用 Claude Code 编写程序。"}
    raw = {"article_type":"story", "slots":[{"id": "cover" if i == 0 else f"body-{i}", "form":"cover" if i == 0 else "timeline", "headline":"积分发了两次", "source_quote":article["markdown"]} for i in range(4)]}
    monkeypatch.setattr(article_visual, "_text_with_deadline", lambda *args, **kwargs: '{"passed": false, "reason":"不相关"}')
    with pytest.raises(ValueError, match="事实复核"):
        article_visual.verify_plan_semantics(raw, article)


def test_digest_changes_if_article_url_title_or_body_changes():
    article = {"url":"https://mp.weixin.qq.com/s/a", "title":"标题", "markdown":"正文"}
    for key in article:
        changed = dict(article, **{key: article[key] + "变化"})
        assert article_visual.article_digest(changed) != article_visual.article_digest(article)


def test_model_review_accepts_paraphrase_and_rejects_uncertain(monkeypatch):
    import pytest
    article = {"title":"前演员转行程序员", "markdown":"她退役后学习编程，使用 AI 编写程序。"}
    raw = {"slots": [{"headline":"用 AI 开启第二人生"}]}
    monkeypatch.setattr(article_visual, "_text_with_deadline", lambda *a, **k: '{"passed": true}')
    article_visual.verify_plan_semantics(raw, article)
    monkeypatch.setattr(article_visual, "_text_with_deadline", lambda *a, **k: '{"passed": "true"}')
    with pytest.raises(ValueError):
        article_visual.verify_plan_semantics(raw, article)


def test_missing_numbers_are_rejected():
    import pytest
    article = {"title":"转行程序员", "markdown":"她退役后开始学习编程，并使用 AI 编写程序。"}
    raw = {"article_type":"story", "slots":[{"id":"cover" if i == 0 else f"body-{i}", "form":"cover" if i == 0 else "timeline", "headline":"学习编程赚了1000万", "source_quote":article["markdown"]} for i in range(4)]}
    with pytest.raises(ValueError, match="数字"):
        article_visual.validate_plan(raw, article)


def test_repeated_paragraphs_are_preserved():
    html = '<meta property="og:title" content="标题"><div id="js_content"><p>她开始学习编程</p><p>她开始学习编程</p></div>'
    assert article_visual.parse_article_html(html)["markdown"].count("她开始学习编程") == 2


def test_article_types_are_supported():
    article = {"title":"内容", "markdown":"这是文章中用于验证的连续原文片段。"}
    for kind in ["story", "event", "knowledge", "opinion", "review", "interview", "mixed"]:
        raw = {"article_type":kind, "slots":[{"id":"cover" if i == 0 else f"body-{i}", "form":"cover" if i == 0 else "timeline", "headline":"文章内容", "source_quote":article["markdown"]} for i in range(4)]}
        article_visual.validate_plan(raw, article)


def test_plan_accepts_a_single_cover_without_body_slots():
    article = {"title":"短篇报道标题", "markdown":"这是文章中用于验证的连续原文片段。"}
    raw = {"article_type":"event", "slots":[{"id":"cover", "form":"cover", "headline":"短篇报道标题", "source_quote":article["markdown"]}]}
    article_visual.validate_plan(raw, article)
    plan = article_visual._normalize_plan(raw, article)
    assert len(plan["slots"]) == 1


def test_direction_choices_keep_independent_slots_and_evidence():
    article = {"title":"演员转行程序员", "account":"", "markdown":"她退役后学习编程并使用 AI 写程序。"}
    choices = []
    for direction in ["身份反差", "技术探索", "职业转型"]:
        raw = {"angle_label":direction, "article_type":"story", "slots":[{"id":"cover" if i == 0 else f"body-{i}", "form":"cover" if i == 0 else "timeline", "headline":direction, "source_quote":article["markdown"]} for i in range(4)]}
        article_visual.validate_plan(raw, article)
        choices.append(article_visual._normalize_plan(raw, article))
    assert [c["slots"][0]["headline"] for c in choices] == ["身份反差", "技术探索", "职业转型"]
    assert choices[0]["slots"][0]["source_quote"] == article["markdown"]


def test_switch_angle_preserves_existing_images(tmp_path, monkeypatch):
    from copy import deepcopy
    from types import SimpleNamespace
    from server import article_visual as av
    monkeypatch.setattr(av, "JOBS_DIR", tmp_path)
    monkeypatch.setattr(av.accounts, "require_user", lambda request: {"id":"u1"})
    choices = [{"slots":[{"id":"cover", "form":"cover", "headline":str(i)}], "thesis":str(i), "article_type":"story", "angle_label":str(i), "angle_reason":""} for i in range(3)]
    original = {"id":"original", "user_id":"u1", "article":{"title":"a"}, "plan":{"slots":choices[0]["slots"], "alternatives":choices, "selected_angle":0}, "images":{"cover":{"file":"cover.png"}}}
    (tmp_path / "original").mkdir()
    (tmp_path / "original" / "article.md").write_text("original content", encoding="utf-8")
    saved = []
    monkeypatch.setattr(av, "_read_job", lambda ident:deepcopy(original))
    monkeypatch.setattr(av, "_write_job", lambda job:saved.append(deepcopy(job)))
    result = av.select_angle("original", av.AngleBody(index=1), SimpleNamespace())
    assert result["id"] != "original"
    assert result["images"] == {}
    assert result["slots"][0]["headline"] == "1"
    assert original["images"]["cover"]["file"] == "cover.png"
    assert (tmp_path / result["id"] / "article.md").read_text(encoding="utf-8") == "original content"


def test_sticker_page_reports_correct_format_instead_of_missing_article():
    html = """<html><script>var picture_page_info_list: [
      {cdn_url: 'https://mmbiz.qpic.cn/example/0'}];</script></html>"""
    with pytest.raises(ValueError, match='这是贴图号图文'):
        article_visual.parse_article_html(html)
    with pytest.raises(ValueError, match='暂时无法读取文章正文'):
        article_visual.parse_article_html('<html><script>picture_page_info_list: []</script></html>')


def test_sticker_format_is_not_fetched_twice(monkeypatch):
    class Response:
        text = "<script>picture_page_info_list: [{cdn_url:'https://mmbiz.qpic.cn/example/0'}]</script>"
        def raise_for_status(self): pass
    calls = []
    monkeypatch.setattr(article_visual.requests, 'get', lambda *a, **k: (calls.append(True), Response())[1])
    with pytest.raises(ValueError, match='这是贴图号图文'):
        article_visual.extract_article('https://mp.weixin.qq.com/s/sticker-example')
    assert len(calls) == 1


def test_parse_js_content_single_quoted_html():
    html = "<html><div id='js_content'><p>这是一段正常文章正文。</p></div></html>"
    assert '这是一段正常文章正文' in article_visual.parse_article_html(html)['markdown']


def test_extract_json_repairs_unescaped_quotes_inside_model_strings():
    # 线上 2026-11-07 的真实失败形态：模型把原文里的 "老同学" 原样塞进
    # source_quote，裸引号提前结束 JSON 字符串，整份方案解析失败。
    raw = '''```json
{"plans": [{"article_type": "opinion", "slots": [
  {"id": "cover", "form": "cover",
   "headline": "一声小猴紫，观众想起了不同作品",
   "source_quote": "一句"老同学"，一声"小猴紫"，杨紫生日时收到的祝福，把观众的记忆带回了不同的作品",
   "items": ["从"小雪"到不同角色，称呼记录职业轨迹", "角色印记比社交热度更能说明演员轨迹"],
   "brief": "成年女演员在片场工作的场景"}
]}]}
```'''
    result = article_visual._extract_json(raw)
    slot = result['plans'][0]['slots'][0]
    assert slot['source_quote'].startswith('一句"老同学"，一声"小猴紫"')
    assert slot['items'][0] == '从"小雪"到不同角色，称呼记录职业轨迹'


def test_extract_json_keeps_valid_json_and_literal_brackets_intact():
    assert article_visual._extract_json('{"a": "x\\"y"}') == {'a': 'x"y'}
    assert article_visual._extract_json('{"a": "x,}"}') == {'a': 'x,}'}


def test_extract_json_drops_trailing_comma_from_model_output():
    assert article_visual._extract_json('{"plans": [{"slots": [1, 2,],}],}') == {
        'plans': [{'slots': [1, 2]}]
    }
