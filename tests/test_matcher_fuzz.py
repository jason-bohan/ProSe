"""Fuzz/emulation testing for the violation matcher using synthetic data
generated in place of hand-picked fixtures (stdlib stand-in for Faker).

Goal: the matcher must never crash or return an out-of-range confidence on
any shape of violation/record the crawler or a user upload could produce,
and its documented invariants (window bounds, threshold, opt-out) must hold
across many randomized cases, not just the handful in test_matcher.py.
"""

from __future__ import annotations

from prose.matcher import evaluate
from tests.emulation.synthetic import synthetic_pairs

SEED = 20260930
SAMPLE_SIZE = 500


def test_matcher_never_crashes_or_produces_invalid_confidence() -> None:
    for violation, record in synthetic_pairs(SEED, SAMPLE_SIZE):
        result = evaluate(violation, record)
        if result is not None:
            assert 0.0 <= result.confidence <= 1.0
            assert result.evidence
            assert result.claim_type == violation.claim_type


def test_matcher_recall_matches_only_within_window() -> None:
    hits = 0
    for violation, record in synthetic_pairs(SEED, SAMPLE_SIZE):
        if violation.rules[0]["type"] != "recall":
            continue
        result = evaluate(violation, record)
        if result is None:
            continue
        hits += 1
        skus = set(violation.rules[0]["recall_skus"])
        matched_purchases = [
            p
            for p in record.purchases
            if p.sku in skus and violation.window_start <= p.purchased_on <= violation.window_end
        ]
        assert matched_purchases, "match fired with no purchase inside the recall window"
    assert hits > 0, "synthetic data never produced a recall match; widen generator hit chance"


def test_matcher_overcharge_respects_threshold() -> None:
    hits = 0
    for violation, record in synthetic_pairs(SEED, SAMPLE_SIZE):
        rule = violation.rules[0]
        if rule["type"] != "overcharge":
            continue
        result = evaluate(violation, record)
        if result is None:
            continue
        hits += 1
        assert f"${rule['threshold']:.2f})" in result.evidence[0]
    assert hits > 0


def test_matcher_auto_enroll_ignores_opted_out_subscriptions() -> None:
    for violation, record in synthetic_pairs(SEED, SAMPLE_SIZE):
        if violation.rules[0]["type"] != "auto_enroll":
            continue
        result = evaluate(violation, record)
        if result is None:
            continue
        live_subs = [s for s in record.subscriptions if s.auto_renew and not s.opted_out]
        assert len(result.evidence) == len(live_subs)


def test_synthetic_pairs_are_deterministic_for_a_given_seed() -> None:
    first = synthetic_pairs(SEED, 20)
    second = synthetic_pairs(SEED, 20)
    assert [v.id for v, _ in first] == [v.id for v, _ in second]
    assert [r.party for _, r in first] == [r.party for _, r in second]
