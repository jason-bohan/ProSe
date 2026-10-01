from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

STAGES: tuple[str, ...] = (
    "PRE_FILED",
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
)

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "PRE_FILED": ("FILED",),
    "FILED": ("SERVICE",),
    "SERVICE": ("ANSWER_DUE",),
    "ANSWER_DUE": ("ANSWERED",),
    "ANSWERED": ("INITIAL_HEARING", "MOTIONS"),
    "INITIAL_HEARING": ("DISCOVERY",),
    "DISCOVERY": ("MOTIONS", "TRIAL"),
    "MOTIONS": ("TRIAL", "JUDGMENT"),
    "TRIAL": ("JUDGMENT",),
    "JUDGMENT": ("CLOSED",),
    "CLOSED": (),
}


class TransitionError(Exception):
    pass


@dataclass
class Case:
    case_number: str
    party: str
    cause: str
    stage: str = "PRE_FILED"
    history: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise TransitionError(f"unknown stage: {self.stage}")
        self.history.append((date.today().isoformat(), f"{self.stage}: case created"))

    def can_transition(self, stage: str) -> bool:
        return stage in TRANSITIONS.get(self.stage, ())

    def advance(self, stage: str, note: str = "") -> None:
        if not self.can_transition(stage):
            allowed = TRANSITIONS.get(self.stage, ())
            raise TransitionError(f"cannot move {self.stage} -> {stage}; allowed: {allowed}")
        self.stage = stage
        self.history.append((date.today().isoformat(), f"{stage}: {note}".strip(": ")))