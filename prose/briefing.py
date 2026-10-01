from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class StageBriefing:
    stage: str
    title: str
    checklist: tuple[str, ...]
    caution: str

    def to_text(self) -> str:
        lines = [f"STAGE {self.stage} - {self.title.upper()}"]
        lines.extend(f"  [ ] {item}" for item in self.checklist)
        lines.append(f"  CAUTION: {self.caution}")
        return "\n".join(lines)


def load_briefings() -> dict[str, StageBriefing]:
    path = DATA_DIR / "briefings.json"
    with path.open(encoding="utf-8") as fh:
        records = json.load(fh)
    return {
        record["stage"]: StageBriefing(
            stage=record["stage"],
            title=record["title"],
            checklist=tuple(record["checklist"]),
            caution=record["caution"],
        )
        for record in records
    }


def brief_for_stage(stage: str) -> StageBriefing:
    briefings = load_briefings()
    if stage not in briefings:
        raise KeyError(f"no pre-prepared briefing for stage: {stage}")
    return briefings[stage]