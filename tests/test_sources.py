from __future__ import annotations

from datetime import date

import prose.crawler as crawler
from prose.crawler import (
    CfpbSource,
    FtcSource,
    MockPACERSource,
    RecapSource,
    Source,
    collect,
    derive_rules,
)
from prose.pipeline import run

CPFB_FIXTURE = {
    "hits": {
        "hits": [
            {
                "_id": "12345",
                "_source": {
                    "complaint_id": "12345",
                    "product": "Credit card or prepaid card",
                    "sub_product": "Credit card",
                    "issue": "Charged in error",
                    "sub_issue": "Charged for unauthorized auto-renewal",
                    "company": "ACME SUBS LLC",
                    "date_received": "2026-08-01T12:00:00.000Z",
                    "company_response": "Closed with relief",
                },
            },
            {"_source": {}},
        ]
    }
}

RECAP_FIXTURE = {
    "results": [
        {
            "docket_id": 42,
            "caseName": "Smith v. Acme Subscriptions, Inc.",
            "docketNumber": "1:26-cv-1",
            "court": "D. Mass.",
            "dateFiled": "2026-01-15",
            "dateTerminated": None,
            "party": ["Jane Smith", "Acme Subscriptions, Inc."],
            "recap_documents": [
                {
                    "short_description": (
                        "Class action complaint alleging deceptive auto-renewal of subscription."
                    )
                }
            ],
        },
        {"caseName": "NoDocket v. Case"},
    ]
}

FTC_FIXTURE = (
    b"<?xml version='1.0'?><rss version='2.0'><channel>"
    b"<item><title>FTC sues Acme over hidden fees and deceptive auto-renewal</title>"
    b"<link>https://www.ftc.gov/news-events/news/press-releases/2026/09/acme</link>"
    b"<pubDate>Thu, 17 Sep 2026 08:00:00 -0400</pubDate>"
    b"<description>FTC filed an action today against Acme.</description></item>"
    b"<item><title></title><link>https://www.ftc.gov/x</link>"
    b"<pubDate>Thu, 17 Sep 2026 08:00:00 -0400</pubDate></item>"
    b"</channel></rss>"
)


def test_derive_rules_fee_and_auto_renew_and_sku() -> None:
    rules = derive_rules("We charged a hidden fee and your plan auto-renews. SKU VLX-200 applied.")
    kinds = [rule["type"] for rule in rules]
    assert kinds == ["overcharge", "auto_enroll", "recall"]
    assert rules[0]["fee_description"] == "hidden fee"
    assert rules[2]["recall_skus"] == ["VLX-200"]


def test_derive_rules_empty() -> None:
    assert derive_rules("", "nothing relevant here") == ()


def test_cf_pb_source_parses_hits(monkeypatch) -> None:
    monkeypatch.setattr(crawler, "http_get_json", lambda url: CPFB_FIXTURE)
    violations = CfpbSource(query="auto-renew", size=2).fetch()
    assert len(violations) == 1
    v = violations[0]
    assert v.id == "cfpb-12345"
    assert v.source == "CFPB"
    assert v.status == "closed"
    assert v.window_end == date(2026, 8, 1)
    assert [r["type"] for r in v.rules] == ["auto_enroll"]


def test_cf_pb_source_matches_sample_record(monkeypatch) -> None:
    monkeypatch.setattr(crawler, "http_get_json", lambda url: CPFB_FIXTURE)
    result = run(sources=[CfpbSource()])
    assert len(result.matches) == 1
    assert result.matches[0].violation.id == "cfpb-12345"
    assert result.drafts


def test_recap_source_parses_results(monkeypatch) -> None:
    monkeypatch.setattr(crawler, "http_get_json", lambda url: RECAP_FIXTURE)
    violations = RecapSource().fetch()
    assert len(violations) == 1
    v = violations[0]
    assert v.id == "recap-42"
    assert v.claim_type == "class_claim"
    assert v.status == "open"
    assert "auto_enroll" in [r["type"] for r in v.rules]
    assert v.window_start == date(2026, 1, 15)


def test_recap_source_honors_rows_limit(monkeypatch) -> None:
    monkeypatch.setattr(crawler, "http_get_json", lambda url: RECAP_FIXTURE)
    violations = RecapSource(rows=1).fetch()
    assert [v.id for v in violations] == ["recap-42"]


def test_ftc_source_parses_items(monkeypatch) -> None:
    monkeypatch.setattr(crawler, "http_get", lambda url, accept="": FTC_FIXTURE)
    violations = FtcSource(limit=5).fetch()
    assert len(violations) == 1
    v = violations[0]
    assert v.source == "FTC"
    assert v.id.startswith("ftc-")
    assert v.window_end == date(2026, 9, 17)
    kinds = [r["type"] for r in v.rules]
    assert "overcharge" in kinds
    assert "auto_enroll" in kinds
    assert v.claim_type == "class_claim"


def test_collect_survives_failing_source() -> None:
    class BoomSource(Source):
        name = "Boom"

        def fetch(self) -> list:
            raise urllib_error()

    found = collect([MockPACERSource(), BoomSource()])
    assert len(found) == 2
    assert all(v.source == "PACER" for v in found)


def test_collect_rate_limit_is_accepted() -> None:
    assert collect([MockPACERSource()], rate_limit_seconds=0.0)


def urllib_error() -> OSError:
    return OSError("network down")