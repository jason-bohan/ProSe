from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .crawler import Violation


@dataclass(frozen=True)
class Purchase:
    item: str
    sku: str
    merchant: str
    purchased_on: date
    price: float


@dataclass(frozen=True)
class Subscription:
    name: str
    monthly_fee: float
    auto_renew: bool
    opted_out: bool


@dataclass(frozen=True)
class BankRow:
    posted_on: date
    description: str
    amount: float


@dataclass(frozen=True)
class UserRecord:
    party: str
    purchases: tuple[Purchase, ...] = ()
    subscriptions: tuple[Subscription, ...] = ()
    bank_rows: tuple[BankRow, ...] = ()


@dataclass(frozen=True)
class MatchResult:
    violation: Violation
    evidence: tuple[str, ...]
    confidence: float
    claim_type: str

    def to_summary(self) -> str:
        lines = [
            f"MATCH {self.violation.id} - {self.violation.program}",
            f"  claim type : {self.claim_type}  confidence: {self.confidence:.2f}",
        ]
        lines.extend(f"  evidence   : {item}" for item in self.evidence)
        return "\n".join(lines)


def evaluate(violation: Violation, record: UserRecord) -> MatchResult | None:
    evidence: list[str] = []
    confidence = 0.0
    for rule in violation.rules:
        result = _run_rule(rule, record, violation.window_start, violation.window_end)
        if result is None:
            return None
        evidence.extend(result[0])
        confidence = max(confidence, result[1])
    if not evidence:
        return None
    return MatchResult(violation, tuple(evidence), confidence, violation.claim_type)


def _run_rule(
    rule: dict,
    record: UserRecord,
    window_start: date,
    window_end: date,
) -> tuple[list[str], float] | None:
    kind = rule["type"]
    if kind == "recall":
        return _recall(rule, record, window_start, window_end)
    if kind == "auto_enroll":
        return _auto_enroll(rule, record)
    if kind == "overcharge":
        return _overcharge(rule, record, window_start, window_end)
    raise ValueError(f"unknown rule type: {kind}")


def _recall(
    rule: dict,
    record: UserRecord,
    window_start: date,
    window_end: date,
) -> tuple[list[str], float] | None:
    skus = set(rule.get("recall_skus", ()))
    hits = [
        p
        for p in record.purchases
        if p.sku in skus and window_start <= p.purchased_on <= window_end
    ]
    if not hits:
        return None
    evidence = [
        f"purchased {p.item} ({p.sku}) from {p.merchant} on {p.purchased_on.isoformat()} "
        f"at ${p.price:.2f}"
        for p in hits
    ]
    return evidence, 0.95


def _auto_enroll(rule: dict, record: UserRecord) -> tuple[list[str], float] | None:
    subs = [s for s in record.subscriptions if s.auto_renew and not s.opted_out]
    if not subs:
        return None
    evidence = [
        f"subscription {s.name} ${s.monthly_fee:.2f}/mo renews automatically, never opted out"
        for s in subs
    ]
    return evidence, 0.8


def _overcharge(
    rule: dict,
    record: UserRecord,
    window_start: date,
    window_end: date,
) -> tuple[list[str], float] | None:
    term = rule.get("fee_description", "").lower().strip()
    if not term:
        return None
    rows = [
        r
        for r in record.bank_rows
        if term in r.description.lower() and window_start <= r.posted_on <= window_end
    ]
    total = sum(r.amount for r in rows)
    threshold = float(rule.get("threshold", float("inf")))
    if not rows or total <= threshold:
        return None
    evidence = [
        f"{len(rows)} '{term}' entries totaling ${total:.2f} between "
        f"{window_start.isoformat()} and {window_end.isoformat()} "
        f"(threshold ${threshold:.2f})"
    ]
    return evidence, 0.7