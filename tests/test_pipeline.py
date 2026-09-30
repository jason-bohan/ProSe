from __future__ import annotations

from prose.matcher import UserRecord
from prose.pipeline import MIN_AUTO_CONFIDENCE, SAMPLE_TRANSCRIPT, run


def test_crawler_feeds_matcher_and_review_split() -> None:
    result = run()
    assert result.total_violations == 3
    assert len(result.matches) == 2
    assert len(result.review) == 1
    assert len(result.matches) + len(result.review) == 3


def test_confidence_threshold_split() -> None:
    result = run()
    assert all(m.confidence >= MIN_AUTO_CONFIDENCE for m in result.matches)
    assert all(m.confidence < MIN_AUTO_CONFIDENCE for m in result.review)
    assert result.review[0].violation.id == "fee-2026-118"
    assert result.matches[0].violation.id == "vlm-2026-0147"


def test_match_confidence_ordering() -> None:
    result = run()
    confidences = [m.confidence for m in result.matches]
    assert confidences == sorted(confidences, reverse=True)


def test_case_advanced_to_filed_with_briefing() -> None:
    result = run()
    assert result.case is not None
    assert result.case.stage == "FILED"
    assert any(entry.startswith("FILED") for _, entry in result.case.history)
    assert result.briefing is not None
    assert result.briefing.stage == "FILED"


def test_drafts_generated_only_for_auto_matches() -> None:
    result = run()
    assert len(result.drafts) == 2
    doc_types = {d.doc_type for _, d in result.drafts}
    assert doc_types == {"class_claim", "complaint"}
    assert result.review[0].violation.id not in {vid for vid, _ in result.drafts}


def test_entity_tags_computed() -> None:
    result = run()
    assert result.tags is not None
    assert result.tags.is_class_action is True
    assert "Janet A. Doe" in result.tags.parties
    assert "$30.00" in result.tags.amounts


def test_hud_flags_every_core_objection() -> None:
    result = run()
    flagged = {o.rule_id for frame in result.frames for o in frame.objections}
    assert flagged == {
        "speculation",
        "leading",
        "hearsay",
        "foundation",
        "best_evidence",
        "argument",
    }


def test_hud_prompt_present_when_objection_fired() -> None:
    result = run()
    fired = [f for f in result.frames if f.objections]
    assert len(fired) == len(result.frames)
    for frame in fired:
        assert frame.prompt is not None
        assert frame.prompt.startswith("OBJECTION:")


def test_render_text_contains_disclaimer_and_sections() -> None:
    result = run()
    text = result.to_text()
    assert "Not legal advice" in text
    assert "Crawled violations" in text
    assert "Held for human review" in text
    assert "Entity tags" in text
    assert "Stage briefing" in text
    assert "Glasses HUD" in text
    assert "OBJECTION" in text


def test_empty_record_produces_no_matches() -> None:
    result = run(record=UserRecord(party="No One"), transcript=SAMPLE_TRANSCRIPT)
    assert result.matches == []
    assert result.review == []
    assert result.case is None
    assert result.briefing is None
    assert result.drafts == []
    assert result.total_violations == 3
    assert len(result.frames) == len(SAMPLE_TRANSCRIPT)


def test_custom_raw_text_flowst_through_tagger() -> None:
    result = run(raw_text="Defendant: Mega Corp settled the class action on 2026-03-01.")
    assert result.tags is not None
    assert result.tags.parties == ("Mega Corp",)
    assert "2026-03-01" in result.tags.dates