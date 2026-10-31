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
    assert len(plan["slots"]) == 5  # 1 封面 + 最多 4 个正文
    assert [s["order"] for s in plan["slots"]] == [0, 1, 2, 3, 4]
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
    assert "只有物件与光影" in prompt
