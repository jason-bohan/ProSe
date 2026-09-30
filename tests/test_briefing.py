from __future__ import annotations

import pytest

from prose.briefing import brief_for_stage, load_briefings
from prose.state_machine import STAGES


def test_briefing_for_known_stage() -> None:
    briefing = brief_for_stage("DISCOVERY")
    assert briefing.stage == "DISCOVERY"
    assert len(briefing.checklist) >= 3
    assert briefing.caution
    text = briefing.to_text()
    assert text.startswith("STAGE DISCOVERY")
    assert "CAUTION:" in text


def test_brief_all_known_stages() -> None:
    by_stage = load_briefings()
    for stage in STAGES:
        assert stage in by_stage, stage
        assert brief_for_stage(stage).checklist


def test_unknown_stage_raises() -> None:
    with pytest.raises(KeyError):
        brief_for_stage("BOGUS")


def test_case_stage_briefings_align() -> None:
    for stage in STAGES:
        assert brief_for_stage(stage).stage == stage