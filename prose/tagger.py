from __future__ import annotations

import re
from dataclasses import dataclass

DATE_RE = re.compile(
    r"\b(?:19|20)\d{2}-\d{2}-\d{2}\b"
    r"|\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+(?:19|20)\d{2}\b"
)
CURRENCY_RE = re.compile(r"\$\s?\d[\d,]*\.?\d*")
PARTY_RE = re.compile(
    r"\b(?:Plaintiff|Defendant|Claimant|Respondent)s?: "
    r"([A-Z][A-Za-z0-9.'-]*(?: [A-Z][A-Za-z0-9.'-]*){0,4})"
)
CLASS_ACTION_RE = re.compile(
    r"\bclass action|class-wide|certified class|on behalf of the class\b", re.IGNORECASE
)

VIOLATION_KEYWORDS = (
    "auto-renew",
    "auto renewal",
    "hidden fee",
    "late fee",
    "deceptive",
    "false advertising",
    "unauthorized",
    "refund",
    "settlement",
    "class action",
)

SAMPLE_RAW_COMPLAINT = (
    "Plaintiff: Janet A. Doe\n"
    "Defendant: Voltmax Direct LLC\n"
    "Filed: 2026-09-12\n"
    "\n"
    "On behalf of the class, Plaintiff alleges defendant marketed the VLX-200 as a\n"
    "20,000 mAh battery while shipping 8,500 mAh units, and charged a hidden late fee\n"
    "of $30.00 on 2025-07-02. Plaintiff seeks a class action settlement and a full\n"
    "refund of $59.99."
)


@dataclass(frozen=True)
class TagSet:
    dates: tuple[str, ...] = ()
    amounts: tuple[str, ...] = ()
    parties: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    is_class_action: bool = False

    def to_dict(self) -> dict:
        return {
            "dates": list(self.dates),
            "amounts": list(self.amounts),
            "parties": list(self.parties),
            "keywords": list(self.keywords),
            "is_class_action": self.is_class_action,
        }

    def summary(self) -> str:
        def fmt(values: tuple[str, ...]) -> str:
            return ", ".join(values) if values else "(none)"

        class_action = "yes" if self.is_class_action else "no"
        return "\n".join(
            [
                f"dates      : {fmt(self.dates)}",
                f"amounts    : {fmt(self.amounts)}",
                f"parties    : {fmt(self.parties)}",
                f"keywords   : {fmt(self.keywords)}",
                f"class_action: {class_action}",
            ]
        )


def tag_text(text: str) -> TagSet:
    dates = tuple(sorted(set(DATE_RE.findall(text))))
    amounts = tuple(sorted(set(CURRENCY_RE.findall(text))))
    parties = tuple(dict.fromkeys(PARTY_RE.findall(text)))
    lowered = text.lower()
    keywords = tuple(k for k in VIOLATION_KEYWORDS if k in lowered)
    is_class_action = bool(CLASS_ACTION_RE.search(text))
    return TagSet(
        dates=dates,
        amounts=amounts,
        parties=parties,
        keywords=keywords,
        is_class_action=is_class_action,
    )