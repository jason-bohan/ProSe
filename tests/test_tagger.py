from __future__ import annotations

from pathlib import Path

from prose.tagger import SAMPLE_RAW_COMPLAINT, tag_text


def test_sample_text_tags_fully() -> None:
    tags = tag_text(SAMPLE_RAW_COMPLAINT)
    assert "2026-09-12" in tags.dates
    assert "2025-07-02" in tags.dates
    assert "$30.00" in tags.amounts
    assert "$59.99" in tags.amounts
    assert tags.parties == ("Janet A. Doe", "Voltmax Direct LLC")
    assert "class action" in tags.keywords
    assert "late fee" in tags.keywords
    assert "refund" in tags.keywords
    assert tags.is_class_action is True


def test_month_day_year_date_form() -> None:
    tags = tag_text("Filed January 5, 2026. Refund of $12.34 requested.")
    assert "January 5, 2026" in tags.dates
    assert "$12.34" in tags.amounts


def test_empty_text_has_no_tags() -> None:
    tags = tag_text("")
    assert tags.to_dict() == {
        "dates": [],
        "amounts": [],
        "parties": [],
        "keywords": [],
        "is_class_action": False,
    }


def test_non_class_document() -> None:
    tags = tag_text("Plaintiff: Joan U. Smith filed a claim on 2026-01-02 for $5.00.")
    assert tags.parties == ("Joan U. Smith",)
    assert tags.is_class_action is False


def test_summary_renders_lines() -> None:
    text = tag_text(SAMPLE_RAW_COMPLAINT).summary()
    assert "dates" in text
    assert "class_action: yes" in text


def test_parties_deduplicated_by_label() -> None:
    text = "Plaintiff: A. B. C.\nPlaintiff: A. B. C.\nDefendant: D. E. LLC"
    assert tag_text(text).parties == ("A. B. C.", "D. E. LLC")


def test_file_input_via_tmp_doc(tmp_path: Path) -> None:
    doc = tmp_path / "raw.txt"
    raw = "Defendant: Zeta Corp sought class action relief on 2026-02-02."
    doc.write_text(raw, encoding="utf-8")
    tags = tag_text(doc.read_text(encoding="utf-8"))
    assert tags.parties == ("Zeta Corp",)
    assert tags.is_class_action is True