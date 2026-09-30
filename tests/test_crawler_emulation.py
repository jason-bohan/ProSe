"""Emulation tests for prose.crawler: exercise the real HTTP code path
(URL construction, gzip decoding, headers, timeouts, malformed responses)
against a local mock server instead of monkeypatching http_get/http_get_json.

This is the network-layer complement to tests/test_sources.py, which stubs
the parsing functions directly.
"""

from __future__ import annotations

import json

import pytest

import prose.crawler as crawler
from prose.crawler import CfpbSource, FtcSource, MockPACERSource, RecapSource, collect
from tests.emulation.mock_endpoints import MockRegulatoryServer, Route

CPFB_FIXTURE = {
    "hits": {
        "hits": [
            {
                "_source": {
                    "complaint_id": "12345",
                    "product": "Credit card or prepaid card",
                    "issue": "Charged for unauthorized auto-renewal",
                    "company": "ACME SUBS LLC",
                    "date_received": "2026-08-01T12:00:00.000Z",
                    "company_response": "Closed with relief",
                },
            },
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
                {"short_description": "Class action complaint alleging deceptive auto-renewal."}
            ],
        },
    ]
}

FTC_FIXTURE = (
    b"<?xml version='1.0'?><rss version='2.0'><channel>"
    b"<item><title>FTC sues Acme over hidden fees and deceptive auto-renewal</title>"
    b"<link>https://www.ftc.gov/news-events/news/press-releases/2026/09/acme</link>"
    b"<pubDate>Thu, 17 Sep 2026 08:00:00 -0400</pubDate>"
    b"<description>FTC filed an action today against Acme.</description></item>"
    b"</channel></rss>"
)


def test_cfpb_source_over_real_http_with_gzip(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(CPFB_FIXTURE).encode("utf-8")
    with MockRegulatoryServer({"/cfpb": Route(body=body, gzip_encode=True)}) as server:
        monkeypatch.setattr(crawler, "CFPB_API_URL", f"{server.url}/cfpb")
        violations = CfpbSource(query="auto-renew", size=2).fetch()
        request = server.requests[0]
        assert request.headers["Accept-Encoding"].lower() == "gzip"
        assert "ProSeIngestion" in request.headers["User-Agent"]
    assert len(violations) == 1
    assert violations[0].id == "cfpb-12345"


def test_recap_source_over_real_http(monkeypatch: pytest.MonkeyPatch) -> None:
    body = json.dumps(RECAP_FIXTURE).encode("utf-8")
    with MockRegulatoryServer({"/recap": Route(body=body)}) as server:
        monkeypatch.setattr(crawler, "COURT_LISTENER_SEARCH_URL", f"{server.url}/recap")
        violations = RecapSource().fetch()
    assert len(violations) == 1
    assert violations[0].id == "recap-42"


def test_ftc_source_over_real_http_rss() -> None:
    with MockRegulatoryServer({"/ftc": Route(body=FTC_FIXTURE)}) as server:
        violations = FtcSource(feed_url=f"{server.url}/ftc", limit=5).fetch()
    assert len(violations) == 1
    assert violations[0].source == "FTC"


def test_cfpb_source_survives_malformed_json_via_collect(monkeypatch: pytest.MonkeyPatch) -> None:
    with MockRegulatoryServer({"/cfpb": Route(body=b"not json {{{")}) as server:
        monkeypatch.setattr(crawler, "CFPB_API_URL", f"{server.url}/cfpb")
        found = collect([CfpbSource(), MockPACERSource()])
    assert all(v.source == "PACER" for v in found)


def test_cfpb_source_survives_http_error_status_via_collect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with MockRegulatoryServer({"/cfpb": Route(status=503, body=b"service unavailable")}) as server:
        monkeypatch.setattr(crawler, "CFPB_API_URL", f"{server.url}/cfpb")
        found = collect([CfpbSource(), MockPACERSource()])
    assert all(v.source == "PACER" for v in found)


def test_cfpb_source_times_out_and_is_absorbed_by_collect(monkeypatch: pytest.MonkeyPatch) -> None:
    with MockRegulatoryServer({"/cfpb": Route(body=b"{}", delay=0.5)}) as server:
        monkeypatch.setattr(crawler, "CFPB_API_URL", f"{server.url}/cfpb")
        monkeypatch.setattr(crawler, "REQUEST_TIMEOUT", 0.1)
        found = collect([CfpbSource(), MockPACERSource()])
    assert all(v.source == "PACER" for v in found)


def test_unrouted_path_returns_404_and_is_absorbed(monkeypatch: pytest.MonkeyPatch) -> None:
    with MockRegulatoryServer({}) as server:
        monkeypatch.setattr(crawler, "CFPB_API_URL", f"{server.url}/does-not-exist")
        found = collect([CfpbSource()])
    assert found == []
