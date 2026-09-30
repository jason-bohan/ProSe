"""Stdlib synthetic-data generation -- a dependency-free stand-in for Faker.

Produces randomized (but shape-valid) ``Violation`` / ``UserRecord`` graphs so
the matcher and document pipeline can be fuzzed across many claim shapes
instead of only the handful of fixtures in ``tests/test_matcher.py``.
Everything is driven off a seeded ``random.Random`` so failures reproduce.
"""

from __future__ import annotations

import random
import uuid
from datetime import date, timedelta

from prose.crawler import Violation
from prose.matcher import BankRow, Purchase, Subscription, UserRecord

RULE_TYPES = ("recall", "auto_enroll", "overcharge")
FEE_TERMS = ("late fee", "hidden fee", "setup fee", "activation fee", "annual fee")
CLAIM_TYPES = ("class_claim", "complaint", "arbitration")
MERCHANTS = ("Voltmax Direct", "ShopCo", "ACME Subs LLC", "Newsly", "FitTrack")


def _random_date(rng: random.Random, start_year: int = 2023, end_year: int = 2026) -> date:
    start = date(start_year, 1, 1).toordinal()
    end = date(end_year, 12, 31).toordinal()
    return date.fromordinal(rng.randint(start, end))


def _random_window(rng: random.Random) -> tuple[date, date]:
    start = _random_date(rng, 2023, 2025)
    end = start + timedelta(days=rng.randint(30, 900))
    return start, end


def _random_sku(rng: random.Random) -> str:
    letters = "".join(rng.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=rng.randint(2, 5)))
    digits = "".join(rng.choices("0123456789", k=rng.randint(2, 6)))
    return f"{letters}-{digits}"


def random_rule(rng: random.Random, kind: str | None = None) -> dict:
    kind = kind or rng.choice(RULE_TYPES)
    if kind == "recall":
        skus = [_random_sku(rng) for _ in range(rng.randint(1, 3))]
        return {"type": "recall", "recall_skus": skus}
    if kind == "auto_enroll":
        return {"type": "auto_enroll"}
    if kind == "overcharge":
        return {
            "type": "overcharge",
            "fee_description": rng.choice(FEE_TERMS),
            "threshold": round(rng.uniform(5.0, 100.0), 2),
        }
    raise ValueError(f"unknown rule kind: {kind}")


def random_violation(rng: random.Random, *, rule_kind: str | None = None) -> Violation:
    window_start, window_end = _random_window(rng)
    rule = random_rule(rng, rule_kind)
    return Violation(
        id=f"synthetic-{uuid.UUID(int=rng.getrandbits(128))}",
        program=f"Synthetic Program {rng.randint(1, 9999)}",
        source=rng.choice(("PACER", "CFPB", "RECAP", "FTC")),
        status=rng.choice(("open", "closed", "certified")),
        window_start=window_start,
        window_end=window_end,
        claim_type=rng.choice(CLAIM_TYPES),
        rules=(rule,),
        description="synthetic fixture for fuzz testing",
    )


def random_user_record(rng: random.Random, *, violation: Violation | None = None) -> UserRecord:
    """Generate a user record. When ``violation`` is given, occasionally seed
    data that satisfies its rule so both the match and no-match paths get
    exercised, not just noise that never matches anything."""
    hit_chance = 0.5 if violation is not None else 0.0
    rule = violation.rules[0] if violation and violation.rules else None

    purchases = []
    for _ in range(rng.randint(0, 3)):
        sku = _random_sku(rng)
        if rule and rule["type"] == "recall" and rng.random() < hit_chance:
            sku = rng.choice(rule["recall_skus"])
        if violation and rng.random() < hit_chance:
            span = max(1, (violation.window_end - violation.window_start).days)
            purchased_on = violation.window_start + timedelta(days=rng.randint(0, span))
        else:
            purchased_on = _random_date(rng)
        purchases.append(
            Purchase(
                item=f"Item {rng.randint(1, 999)}",
                sku=sku,
                merchant=rng.choice(MERCHANTS),
                purchased_on=purchased_on,
                price=round(rng.uniform(5.0, 500.0), 2),
            )
        )

    subscriptions = [
        Subscription(
            name=f"Sub{rng.randint(1, 99)}",
            monthly_fee=round(rng.uniform(1.0, 50.0), 2),
            auto_renew=rng.random() < 0.7,
            opted_out=rng.random() < 0.3,
        )
        for _ in range(rng.randint(0, 3))
    ]
    if rule and rule["type"] == "auto_enroll" and rng.random() < hit_chance:
        subscriptions.append(
            Subscription(name="MatchSub", monthly_fee=9.99, auto_renew=True, opted_out=False)
        )

    bank_rows = []
    for _ in range(rng.randint(0, 5)):
        description = f"PURCHASE {rng.randint(1000, 9999)}"
        posted_on = _random_date(rng)
        if rule and rule["type"] == "overcharge" and rng.random() < hit_chance:
            description = f"{rule['fee_description'].upper()} CHARGE"
            posted_on = violation.window_start + timedelta(
                days=rng.randint(0, max(1, (violation.window_end - violation.window_start).days))
            )
        amount = round(rng.uniform(1.0, 60.0), 2)
        bank_rows.append(BankRow(posted_on=posted_on, description=description, amount=amount))

    return UserRecord(
        party=f"Synthetic User {rng.randint(1, 9999)}",
        purchases=tuple(purchases),
        subscriptions=tuple(subscriptions),
        bank_rows=tuple(bank_rows),
    )


def synthetic_pairs(seed: int, count: int) -> list[tuple[Violation, UserRecord]]:
    rng = random.Random(seed)
    pairs = []
    for _ in range(count):
        violation = random_violation(rng)
        record = random_user_record(rng, violation=violation)
        pairs.append((violation, record))
    return pairs
