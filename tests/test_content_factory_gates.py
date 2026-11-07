from server.content_factory_gates import article_gate, image_gate


SOURCE = {"id": "source-1", "title": "来源标题", "url": "https://example.com/a",
          "observed_at": "2026-11-07"}


def editorial(*, title_issues=(), evidence_issues=(), compliance=(), substantive=(), confirm=()):
    return {
        "scores": {"total": 75},
        "editorial_gate": {"status": "human_review", "blockers": [], "revisions": [], "confirmations": []},
        "source_ledger": [],
        "compliance": list(compliance),
        "content_risk": {"substantive": list(substantive), "confirm": list(confirm), "machine": []},
        "evidence": [*title_issues, *evidence_issues],
        "ai_smell": {"risk": 10, "findings": []},
    }


def test_article_gate_accepts_bounded_original_claim_free_draft():
    title = "家庭沟通从听懂开始"
    body = ("家庭沟通里，听懂比急着解释更重要。" + "先弄清对方在意的具体问题，" * 30
            + "再说明自己的边界和能做到的事情。")
    result = article_gate(title=title, content=body, source=SOURCE, editorial=editorial())
    assert all(result["checks"].values())
    assert result["reasons"] == []


def test_article_gate_fails_closed_for_claims_rights_and_title():
    title = "家庭沟通从听懂开始"
    body = ("我采访过三位妈妈，她们都说90%的家庭会吵架。" + "先弄清对方在意的具体问题，" * 30)
    result = article_gate(title=title, content=body, source=SOURCE,
                          editorial=editorial(title_issues=[{"type": "alignment", "severity": "review"}]))
    assert not result["checks"]["facts"]
    assert not result["checks"]["title_consistency"]
    assert "numeric_claim_requires_source" in result["reasons"]
    assert "first_person_experience_unconfirmed" in result["reasons"]


def test_article_gate_rejects_copied_source_title_and_safety_issues():
    source = {**SOURCE, "title": "家庭沟通从听懂开始"}
    result = article_gate(title="家庭沟通从听懂开始", content="先弄清对方在意的具体问题。" * 50,
                          source=source, editorial=editorial(
                              compliance=[{"severity": "warn", "line": "标题党"}]))
    assert not result["checks"]["copyright"]
    assert not result["checks"]["safety"]
    assert "title_too_similar_to_source" in result["reasons"]
    assert "compliance_review_required" in result["reasons"]


def test_image_gate_requires_real_vision_and_glyph_results():
    base = dict(title="家庭沟通从听懂开始", image_text="慢一点说", caption="留出说话的空间",
                source=SOURCE, technical={"image_decode": True, "image_dimensions": True},
                render_checks={"text_exact": True, "text_fits": True, "glyph_coverage": True,
                               "safe_area": True, "contrast": True}, editorial=editorial())
    failed = image_gate(**base, vision={"status": "failed"})
    assert failed["checks"]["visual_quality"] is False
    assert failed["checks"]["image_text"] is False
    vision = {"status": "success", "checks": {
        name: True for name in ("subject_clear", "single_focus", "colors_coherent",
                                "distortion_free", "text_readable", "title_consistent",
                                "copyright_safe", "no_watermark", "no_logo",
                                "no_ip_character", "safe_content")}}
    passed = image_gate(**base, vision=vision)
    assert all(passed["checks"].values())
    assert passed["reasons"] == []
