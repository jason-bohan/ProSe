from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from prose import NOT_LEGAL_ADVICE
from prose.crawler import Violation
from prose.docs import TEMPLATE_DIR, Draft, DraftValidationError, build_docs, render, validate_draft
from prose.matcher import MatchResult

FULL_TOKENS = {
    "PARTY_NAME": "Janet A. Doe",
    "CASE_NO": "26-cv-417",
    "COURT": "United States District Court",
    "DATE": "2026-09-30",
    "PROGRAM": "Test Program",
    "VIOLATION_ID": "v-1",
    "SOURCE": "PACER",
    "CLAIM_TYPE": "CLASS_CLAIM",
    "CONFIDENCE": "95%",
    "EVIDENCE": "  - fact one",
}


def make_match(claim_type: str) -> MatchResult:
    violation = Violation(
        id="v-1",
        program="Test Program",
        source="PACER",
        status="certified",
        window_start=date(2025, 1, 1),
        window_end=date(2026, 12, 31),
        claim_type=claim_type,
        rules=(),
    )
    return MatchResult(violation, ("fact one",), 0.95, claim_type)


def test_all_templates_render_fully() -> None:
    for path in sorted(TEMPLATE_DIR.glob("*.txt")):
        text = render(path.stem, {**FULL_TOKENS, "NOT_LEGAL_ADVICE": NOT_LEGAL_ADVICE})
        assert "{{" not in text, path.stem
        assert NOT_LEGAL_ADVICE in text, path.stem


def test_missing_token_raises() -> None:
    with pytest.raises(KeyError):
        render("complaint", {})


def test_unknown_doc_type_raises() -> None:
    with pytest.raises(KeyError):
        render("nope", FULL_TOKENS)


def test_build_docs_maps_claim_type() -> None:
    assert [d.doc_type for d in build_docs(make_match("class_claim"), **_ctx())] == ["class_claim"]
    assert [d.doc_type for d in build_docs(make_match("complaint"), **_ctx())] == ["complaint"]
    assert (
        [d.doc_type for d in build_docs(make_match("arbitration"), **_ctx())]
        == ["arbitration_letter"]
    )


def test_build_docs_includes_disclaimer_and_party() -> None:
    draft = build_docs(make_match("complaint"), **_ctx())[0]
    assert draft.document_id.startswith("26-cv-417-")
    assert "Janet A. Doe" in draft.text
    assert NOT_LEGAL_ADVICE in draft.text


def test_draft_save_writes_file(tmp_path: Path) -> None:
    draft = build_docs(make_match("complaint"), **_ctx())[0]
    path = draft.save(tmp_path)
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith(NOT_LEGAL_ADVICE)


def test_validate_draft_accepts_good_draft() -> None:
    draft = Draft(
        doc_type="complaint",
        document_id="26-cv-417-complaint",
        text=f"{NOT_LEGAL_ADVICE}\n\nbody",
    )
    validate_draft(draft)


def test_validate_draft_rejects_missing_disclaimer() -> None:
    draft = Draft(doc_type="complaint", document_id="26-cv-417-complaint", text="body only")
    with pytest.raises(DraftValidationError, match="disclaimer"):
        validate_draft(draft)


def test_validate_draft_rejects_unresolved_token() -> None:
    draft = Draft(
        doc_type="complaint",
        document_id="26-cv-417-complaint",
        text=f"{NOT_LEGAL_ADVICE}\n\n{{{{PARTY_NAME}}}}",
    )
    with pytest.raises(DraftValidationError, match="unresolved"):
        validate_draft(draft)


def _ctx() -> dict:
    return {
        "party": "Janet A. Doe",
        "case_number": "26-cv-417",
        "court": "United States District Court",
        "issued": "2026-09-30",
    }