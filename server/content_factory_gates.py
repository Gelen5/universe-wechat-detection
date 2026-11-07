"""Deterministic publication gates built from explicit, auditable evidence.

These gates do not replace fact-checking, legal review or platform review. They
fail closed when the supplied evidence is missing, malformed or contains a
claim that would need a source the generator never received.
"""
from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlparse


SOURCE_ISSUE_TYPES = {"source", "claim_source", "freshness", "claim_freshness", "experience"}
TITLE_ISSUE_TYPES = {"alignment", "title_claim"}
NUMERIC_CLAIM_RE = re.compile(
    r"(?<!\d)(?:\d+(?:\.\d+)?|百分之[零一二三四五六七八九十百]+)"
    r"(?:%|％|万|亿|元|块|岁|天|年|个月|月|日|小时|分钟|秒|次|人|倍|条|篇|个|项|步|种|成|折)"
)
FIRST_PERSON_EXPERIENCE_RE = re.compile(
    r"(?:我|我们)(?:当时|那年|曾经|后来|记得|试过|经历过|遇到|采访过|见过|发现|朋友|邻居|同事|同学|表姐|表哥)"
)
QUOTED_PASSAGE_RE = re.compile(r"[“\"]([^”\"]{80,})[”\"]")


def _norm(value):
    return re.sub(r"\W+", "", unicodedata.normalize("NFKC", value or "").casefold())


def _valid_source(source):
    if not isinstance(source, dict):
        return False
    try:
        parsed = urlparse(source.get("url") or "")
        return (parsed.scheme in ("http", "https") and bool(parsed.hostname)
                and bool(source.get("id")) and bool(source.get("observed_at")))
    except (TypeError, ValueError):
        return False


def _bigrams(value):
    compact = _norm(value)
    return {compact[index:index + 2] for index in range(max(0, len(compact) - 1))}


def _overlap(title, body):
    title_grams = _bigrams(title)
    if not title_grams:
        return 0.0
    return len(title_grams & _bigrams(body)) / len(title_grams)


def _title_similarity(title, source_title):
    left, right = _norm(title), _norm(source_title)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _issue_types(items, field="type"):
    return {item.get(field) for item in items if isinstance(item, dict) and item.get(field)}


def _numeric_claims(text):
    return list(dict.fromkeys(NUMERIC_CLAIM_RE.findall(text or "")))[:10]


def _first_person_claims(text):
    return list(dict.fromkeys(FIRST_PERSON_EXPERIENCE_RE.findall(text or "")))[:10]


def _published_editorial_report(editorial):
    if not isinstance(editorial, dict):
        return {}
    return {
        "gate": editorial.get("editorial_gate"),
        "score": (editorial.get("scores") or {}).get("total"),
        "level": editorial.get("level"),
        "track": editorial.get("track_id"),
        "style": editorial.get("style_id"),
        "claims": (editorial.get("source_ledger") or [])[:10],
        "evidence": (editorial.get("evidence") or [])[:10],
        "compliance": (editorial.get("compliance") or [])[:10],
        "content_risk": {
            "substantive": ((editorial.get("content_risk") or {}).get("substantive") or [])[:5],
            "confirm": ((editorial.get("content_risk") or {}).get("confirm") or [])[:5],
            "machine": ((editorial.get("content_risk") or {}).get("machine") or [])[:5],
        },
        "ai_smell": editorial.get("ai_smell"),
    }


def _fact_check(title, content, source, editorial):
    """Pass only when no supplied claim needs facts unavailable to the writer."""
    reasons = []
    if not _valid_source(source):
        reasons.append("missing_source_evidence")
    if not isinstance(editorial, dict):
        return False, reasons + ["editorial_evidence_unavailable"], {}
    claims = editorial.get("source_ledger")
    evidence = editorial.get("evidence")
    if not isinstance(claims, list) or not isinstance(evidence, list):
        reasons.append("editorial_evidence_incomplete")
        claims, evidence = [], []
    # The production prompt receives the source title only, never the source
    # body. Any identified authority, policy, professional or experience claim
    # therefore lacks evidence that this writer could have relied on.
    unsupported = [item for item in claims if isinstance(item, dict)]
    if unsupported:
        reasons.append("claim_requires_source")
    source_issues = [item for item in evidence if isinstance(item, dict)
                     and item.get("type") in SOURCE_ISSUE_TYPES]
    if source_issues:
        reasons.append("source_or_freshness_issue")
    numbers = _numeric_claims(content)
    if numbers:
        reasons.append("numeric_claim_requires_source")
    experiences = _first_person_claims(content)
    if experiences:
        reasons.append("first_person_experience_unconfirmed")
    report = {
        "source_body_supplied_to_writer": False,
        "source_title_supplied": bool(isinstance(source, dict) and source.get("title")),
        "unsupported_claims": unsupported[:5],
        "source_issues": source_issues[:5],
        "numeric_claims": numbers,
        "first_person_markers": experiences,
    }
    return not reasons, reasons, report


def _copyright_check(title, content, source):
    reasons = []
    source_title = ((source or {}).get("title") or "") if isinstance(source, dict) else ""
    similarity = _title_similarity(title, source_title)
    if source_title and similarity >= 0.72:
        reasons.append("title_too_similar_to_source")
    compact_source = _norm(source_title)
    compact_content = _norm(content)
    if len(compact_source) >= 8 and compact_source in compact_content:
        reasons.append("source_title_copied_verbatim")
    if QUOTED_PASSAGE_RE.search(content or ""):
        reasons.append("long_quotation_needs_rights_review")
    report = {
        "source_title_similarity": round(similarity, 4),
        "source_body_available": False,
        "scope": "source title only; generated text never received the source body",
    }
    return not reasons, reasons, report


def _safety_check(editorial):
    if not isinstance(editorial, dict):
        return False, ["editorial_evidence_unavailable"], {}
    compliance = editorial.get("compliance")
    risk = editorial.get("content_risk")
    if not isinstance(compliance, list) or not isinstance(risk, dict):
        return False, ["safety_evidence_incomplete"], {}
    risky_compliance = [item for item in compliance if isinstance(item, dict)
                        and item.get("severity") in ("block", "warn")]
    substantive = [item for item in risk.get("substantive") or [] if isinstance(item, dict)]
    confirmations = [item for item in risk.get("confirm") or [] if isinstance(item, dict)]
    reasons = []
    if risky_compliance:
        reasons.append("compliance_review_required")
    if substantive:
        reasons.append("substantive_content_risk")
    if confirmations:
        reasons.append("content_risk_needs_confirmation")
    report = {"compliance": risky_compliance[:5], "substantive": substantive[:5],
              "confirmations": confirmations[:5]}
    return not reasons, reasons, report


def _editorial_quality(editorial):
    if not isinstance(editorial, dict):
        return False, ["editorial_evidence_unavailable"], {}
    gate = editorial.get("editorial_gate")
    scores = editorial.get("scores")
    if not isinstance(gate, dict) or not isinstance(scores, dict):
        return False, ["editorial_evidence_incomplete"], {}
    reasons = []
    if gate.get("blockers"):
        reasons.append("editorial_blockers")
    if gate.get("revisions"):
        reasons.append("editorial_revisions_required")
    if gate.get("confirmations"):
        reasons.append("editorial_confirmation_required")
    try:
        total = float(scores.get("total"))
        if not math.isfinite(total) or total < 55:
            reasons.append("editorial_score_below_threshold")
    except (TypeError, ValueError):
        reasons.append("editorial_score_unavailable")
    return not reasons, reasons, {"gate": gate, "score": scores.get("total")}


def _title_check(title, content, editorial):
    if not isinstance(editorial, dict):
        return False, ["editorial_evidence_unavailable"], {}
    evidence = editorial.get("evidence")
    if not isinstance(evidence, list):
        return False, ["title_evidence_unavailable"], {}
    title_issues = [item for item in evidence if isinstance(item, dict)
                    and item.get("type") in TITLE_ISSUE_TYPES]
    overlap = _overlap(title, content)
    reasons = []
    if title_issues:
        reasons.append("title_promise_not_fulfilled")
    if overlap < 0.22:
        reasons.append("title_body_overlap_too_low")
    return not reasons, reasons, {"overlap": round(overlap, 4), "issues": title_issues[:5]}


def article_gate(*, title, content, source, editorial):
    checks, details = {}, {}
    facts, fact_reasons, fact_report = _fact_check(title, content, source, editorial)
    copyright_ok, copy_reasons, copy_report = _copyright_check(title, content, source)
    safety, safety_reasons, safety_report = _safety_check(editorial)
    quality, quality_reasons, quality_report = _editorial_quality(editorial)
    title_ok, title_reasons, title_report = _title_check(title, content, editorial)
    checks.update({"facts": facts, "copyright": copyright_ok, "safety": safety,
                   "title_consistency": title_ok, "editorial_quality": quality})
    details.update({"facts": fact_report, "copyright": copy_report, "safety": safety_report,
                    "editorial_quality": quality_report, "title_consistency": title_report})
    reasons = list(dict.fromkeys(fact_reasons + copy_reasons + safety_reasons
                                 + quality_reasons + title_reasons))
    return {"checks": checks, "reasons": reasons, "details": details,
            "editorial": _published_editorial_report(editorial)}


def image_gate(*, title, image_text, caption, source, technical, render_checks, vision, editorial):
    checks, details = {}, {}
    combined = (image_text or "") + "\n" + (caption or "")
    facts, fact_reasons, fact_report = _fact_check(title, combined, source, editorial)
    copyright_ok, copy_reasons, copy_report = _copyright_check(title, combined, source)
    safety, safety_reasons, safety_report = _safety_check(editorial)
    title_reasons = []
    if not isinstance(editorial, dict):
        title_ok, title_reasons, title_report = False, ["title_evidence_unavailable"], {}
    else:
        evidence = editorial.get("evidence") if isinstance(editorial.get("evidence"), list) else []
        title_issues = [item for item in evidence if isinstance(item, dict)
                        and item.get("type") == "title_claim"]
        title_ok = not title_issues
        if title_issues:
            title_reasons.append("title_promise_not_fulfilled")
        title_report = {"issues": title_issues[:5], "scope": "short-form title checked by vision"}

    vision = vision if isinstance(vision, dict) else {}
    vision_checks = vision.get("checks") if isinstance(vision.get("checks"), dict) else {}
    checked = vision.get("status") == "success"
    vision_visual = all(vision_checks.get(name) is True for name in (
        "subject_clear", "single_focus", "colors_coherent", "distortion_free", "text_readable"))
    vision_safe = checked and vision_checks.get("safe_content") is True
    vision_rights = checked and all(vision_checks.get(name) is True for name in (
        "copyright_safe", "no_watermark", "no_logo", "no_ip_character"))
    vision_title = checked and vision_checks.get("title_consistent") is True

    technical = technical if isinstance(technical, dict) else {}
    render_checks = render_checks if isinstance(render_checks, dict) else {}
    image_text_ok = (all(render_checks.get(name) is True for name in (
        "text_exact", "text_fits", "glyph_coverage", "safe_area", "contrast"))
        and checked and vision_checks.get("text_readable") is True)
    visual_ok = checked and vision_visual
    visual_reasons = []
    if not checked:
        visual_reasons.append("visual_review_unavailable")
    elif not vision_visual:
        visual_reasons.append("visual_quality_failed")
    if not image_text_ok:
        visual_reasons.append("image_text_failed")
    if not vision_safe:
        safety_reasons = safety_reasons + ["visual_safety_failed"]
    if not vision_rights:
        copy_reasons = copy_reasons + ["visual_rights_failed"]
    if not vision_title:
        title_reasons = title_reasons + ["visual_title_inconsistent"]

    checks.update({
        "facts": facts,
        "copyright": copyright_ok and vision_rights,
        "safety": safety and vision_safe,
        "title_consistency": title_ok and vision_title,
        "image_decode": technical.get("image_decode") is True,
        "image_dimensions": technical.get("image_dimensions") is True,
        "image_text": image_text_ok,
        "visual_quality": visual_ok,
        "editorial_quality": safety and facts and title_ok,
    })
    details.update({"facts": fact_report, "copyright": copy_report, "safety": safety_report,
                    "title_consistency": title_report, "vision": vision,
                    "render_checks": render_checks, "technical": technical,
                    "editorial": _published_editorial_report(editorial)})
    reasons = list(dict.fromkeys(fact_reasons + copy_reasons + safety_reasons
                                 + title_reasons + visual_reasons))
    return {"checks": checks, "reasons": reasons, "details": details}
