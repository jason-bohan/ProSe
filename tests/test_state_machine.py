from __future__ import annotations

import pytest

from prose.state_machine import Case, TransitionError


def test_happy_path_full_lifecycle() -> None:
    case = Case(case_number="26-cv-1", party="A. B", cause="Test cause")
    path = [
        "FILED",
        "SERVICE",
        "ANSWER_DUE",
        "ANSWERED",
        "INITIAL_HEARING",
        "DISCOVERY",
        "MOTIONS",
        "TRIAL",
        "JUDGMENT",
        "CLOSED",
    ]
    for stage in path:
        case.advance(stage, f"moved to {stage}")
    assert case.stage == "CLOSED"
    assert case.can_transition("FILED") is False


def test_illegal_transition_raises() -> None:
    case = Case(case_number="26-cv-2", party="A. B", cause="Test cause")
    with pytest.raises(TransitionError):
        case.advance("TRIAL")


def test_alternate_track_motions_before_hearing() -> None:
    case = Case(case_number="26-cv-3", party="A. B", cause="Test cause")
    for stage in ["FILED", "SERVICE", "ANSWER_DUE", "ANSWERED"]:
        case.advance(stage)
    case.advance("MOTIONS", "early dispositive motion")
    assert case.can_transition("TRIAL") is True


def test_history_records_entries() -> None:
    case = Case(case_number="26-cv-4", party="A. B", cause="Test cause")
    case.advance("FILED", "complaint filed")
    assert case.history[0][1] == "PRE_FILED: case created"
    assert case.history[1][1].startswith("FILED")


def test_unknown_stage_rejected() -> None:
    with pytest.raises(TransitionError):
        Case(case_number="26-cv-5", party="A. B", cause="x", stage="BOGUS")