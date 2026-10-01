from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import NOT_LEGAL_ADVICE
from .matcher import MatchResult

TEMPLATE_DIR = Path(__file__).parent / "data" / "templates"

DOC_TYPES_BY_CLAIM: dict[str, tuple[str, ...]] = {
    "class_claim": ("class_claim",),
    "complaint": ("complaint",),
    "arbitration": ("arbitration_letter",),
}


class DraftValidationError(Exception):
    pass


@dataclass(frozen=True)
class Draft:
    doc_type: str
    document_id: str
    text: str

    def save(self, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.document_id}.txt"
        path.write_text(self.text, encoding="utf-8")
        return path


def render(doc_type: str, tokens: dict[str, str]) -> str:
    path = TEMPLATE_DIR / f"{doc_type}.txt"
    if not path.exists():
        raise KeyError(f"no template for doc type: {doc_type}")
    text = path.read_text(encoding="utf-8")
    for key, value in tokens.items():
        text = text.replace("{{" + key + "}}", value)
    missing = re.findall(r"\{\{(\w+)\}\}", text)
    if missing:
        raise KeyError(f"unresolved tokens in {doc_type}: {missing}")
    return text


def validate_draft(draft: Draft) -> None:
    problems: list[str] = []
    if "{{" in draft.text:
        problems.append("unresolved template token")
    if not draft.document_id.strip():
        problems.append("missing document id")
    if NOT_LEGAL_ADVICE not in draft.text:
        problems.append("missing not-legal-advice disclaimer")
    if problems:
        raise DraftValidationError(
            f"draft {draft.doc_type} {draft.document_id}: " + "; ".join(problems)
        )


def build_docs(
    match: MatchResult,
    *,
    party: str,
    case_number: str,
    court: str,
    issued: str,
) -> list[Draft]:
    tokens = {
        "NOT_LEGAL_ADVICE": NOT_LEGAL_ADVICE,
        "PARTY_NAME": party,
        "CASE_NO": case_number,
        "COURT": court,
        "DATE": issued,
        "PROGRAM": match.violation.program,
        "VIOLATION_ID": match.violation.id,
        "SOURCE": match.violation.source,
        "CLAIM_TYPE": match.claim_type.upper(),
        "CONFIDENCE": f"{match.confidence:.0%}",
        "EVIDENCE": "\n".join(f"  - {item}" for item in match.evidence),
    }
    doc_types = DOC_TYPES_BY_CLAIM.get(match.claim_type, ("complaint",))
    drafts = [
        Draft(doc_type=dt, document_id=f"{case_number}-{dt}", text=render(dt, tokens))
        for dt in doc_types
    ]
    for draft in drafts:
        validate_draft(draft)
    return drafts