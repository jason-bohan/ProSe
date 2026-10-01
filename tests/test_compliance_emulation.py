"""Regulatory & compliance emulation gate.

Two cheap, dependency-free stand-ins for the SonarQube/manual-review tooling
in the testing spec:

1. A static-analysis gate (ruff, already a dev dependency) run as part of
   the test suite so lint regressions fail CI, not just local `ruff check`.
2. A scan of every drafted document -- across the full claim-type x doc-type
   matrix, via the real build_docs() pipeline -- for outcome-guaranteeing
   language that would make the "not legal advice" disclaimer misleading.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date

import pytest

from prose import NOT_LEGAL_ADVICE
from prose.crawler import Violation
from prose.docs import DOC_TYPES_BY_CLAIM, build_docs
from prose.matcher import MatchResult

PROHIBITED_CERTAINTY_PATTERNS = (
    r"\bguarantee[sd]?\b",
    r"\bwill win\b",
    r"\bcertain to (succeed|prevail)\b",
    r"\byou will (recover|be awarded)\b",
)


def _make_match(claim_type: str) -> MatchResult:
    violation = Violation(
        id="v-compliance",
        program="Compliance Test Program",
        source="PACER",
        status="certified",
        window_start=date(2025, 1, 1),
        window_end=date(2026, 12, 31),
        claim_type=claim_type,
        rules=(),
    )
    return MatchResult(violation, ("fact one", "fact two"), 0.88, claim_type)


def test_ruff_static_analysis_passes() -> None:
    pytest.importorskip("ruff")
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_full_claim_type_matrix_builds_compliant_drafts() -> None:
    for claim_type in DOC_TYPES_BY_CLAIM:
        drafts = build_docs(
            _make_match(claim_type),
            party="Compliance Tester",
            case_number="26-cv-compliance",
            court="United States District Court",
            issued="2026-09-30",
        )
        for draft in drafts:
            assert draft.text.startswith(NOT_LEGAL_ADVICE)
            assert "{{" not in draft.text


def test_no_outcome_guaranteeing_language_in_generated_drafts() -> None:
    for claim_type in DOC_TYPES_BY_CLAIM:
        drafts = build_docs(
            _make_match(claim_type),
            party="Compliance Tester",
            case_number="26-cv-compliance",
            court="United States District Court",
            issued="2026-09-30",
        )
        for draft in drafts:
            lowered = draft.text.lower()
            for pattern in PROHIBITED_CERTAINTY_PATTERNS:
                assert not re.search(pattern, lowered), (
                    f"{draft.doc_type} contains prohibited certainty language matching {pattern!r}"
                )
