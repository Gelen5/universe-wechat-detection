from server import article_visual


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


def test_cover_prompt_drops_people_scene():
    prompt = article_visual.build_image_prompt(
        {
            "form": "cover",
            "headline": "1270亿女首富",
            "kicker": "2026胡润百富榜",
            "items": ["从流水线女工到女首富", "与马斯克、库克并肩而坐"],
            "brief": "欢迎晚宴圆桌上周群飞与马斯克、库克并肩而坐的场景",
        }
    )
    assert "晚宴圆桌" not in prompt
    assert "一件与文章主题相关的核心物件" in prompt


def test_parse_invalid_link_gets_actionable_hint():
    import pytest

    with pytest.raises(ValueError) as exc:
        article_visual.parse_article_html("<html><body>参数错误</body></html>")
    assert "链接可能被截断" in str(exc.value)



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


def test_direction_choices_keep_independent_slots_and_evidence():
    article = {"title":"演员转行程序员", "account":"", "markdown":"她退役后学习编程并使用 AI 写程序。"}
    choices = []
    for direction in ["身份反差", "技术探索", "职业转型"]:
        raw = {"angle_label":direction, "article_type":"story", "slots":[{"id":"cover" if i == 0 else f"body-{i}", "form":"cover" if i == 0 else "timeline", "headline":direction, "source_quote":article["markdown"]} for i in range(4)]}
        article_visual.validate_plan(raw, article)
        choices.append(article_visual._normalize_plan(raw, article))
    assert [c["slots"][0]["headline"] for c in choices] == ["身份反差", "技术探索", "职业转型"]
    assert choices[0]["slots"][0]["source_quote"] == article["markdown"]
