from __future__ import annotations

from datetime import date

import pytest

from prose.crawler import Violation
from prose.matcher import BankRow, Purchase, Subscription, UserRecord, evaluate


def make_violation(rules) -> Violation:
    return Violation(
        id="v-test",
        program="Test Program",
        source="PACER",
        status="certified",
        window_start=date(2025, 1, 1),
        window_end=date(2026, 12, 31),
        claim_type="class_claim",
        rules=rules,
    )


def make_record() -> UserRecord:
    return UserRecord(
        party="J. R. Tester",
        purchases=(
            Purchase(
                item="Widget",
                sku="W-1",
                merchant="ShopCo",
                purchased_on=date(2025, 5, 1),
                price=19.99,
            ),
        ),
        subscriptions=(
            Subscription(name="FitPlus", monthly_fee=9.99, auto_renew=True, opted_out=False),
            Subscription(name="Newsly", monthly_fee=4.99, auto_renew=True, opted_out=True),
        ),
        bank_rows=(
            BankRow(date(2025, 7, 1), "STORE LATE FEE", 15.00),
            BankRow(date(2025, 8, 1), "STORE LATE FEE", 20.00),
            BankRow(date(2024, 7, 1), "STORE LATE FEE", 99.00),
        ),
    )


def test_recall_hit() -> None:
    violation = make_violation([{"type": "recall", "recall_skus": ["W-1"]}])
    result = evaluate(violation, make_record())
    assert result is not None
    assert result.confidence == 0.95
    assert any("W-1" in e for e in result.evidence)


def test_recall_window_miss() -> None:
    violation = Violation(
        id="v-test",
        program="Test Program",
        source="PACER",
        status="certified",
        window_start=date(2020, 1, 1),
        window_end=date(2020, 12, 31),
        claim_type="class_claim",
        rules=[{"type": "recall", "recall_skus": ["W-1"]}],
    )
    assert evaluate(violation, make_record()) is None


def test_auto_enroll_only_unopted_out_subs() -> None:
    violation = make_violation([{"type": "auto_enroll"}])
    result = evaluate(violation, make_record())
    assert result is not None
    assert len(result.evidence) == 1
    assert "FitPlus" in result.evidence[0]


def test_auto_enroll_all_opted_out() -> None:
    record = UserRecord(
        party="J. R. Tester",
        subscriptions=(
            Subscription(name="Newsly", monthly_fee=4.99, auto_renew=True, opted_out=True),
        ),
    )
    violation = make_violation([{"type": "auto_enroll"}])
    assert evaluate(violation, record) is None


def test_overcharge_above_threshold() -> None:
    violation = make_violation(
        [{"type": "overcharge", "fee_description": "late fee", "threshold": 25.0}]
    )
    result = evaluate(violation, make_record())
    assert result is not None
    assert "35.00" in result.evidence[0]


def test_overcharge_below_threshold() -> None:
    violation = make_violation(
        [{"type": "overcharge", "fee_description": "late fee", "threshold": 100.0}]
    )
    assert evaluate(violation, make_record()) is None


def test_and_semantics_across_rules() -> None:
    violation = make_violation(
        [
            {"type": "recall", "recall_skus": ["W-1"]},
            {"type": "overcharge", "fee_description": "late fee", "threshold": 100.0},
        ]
    )
    assert evaluate(violation, make_record()) is None


def test_unknown_rule_type_raises() -> None:
    violation = make_violation([{"type": "bogus"}])
    with pytest.raises(ValueError, match="bogus"):
        evaluate(violation, make_record())