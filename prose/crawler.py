from __future__ import annotations

import abc
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

USER_AGENT = "ProSeIngestion/0.1 (pro se litigation assist; research use)"
REQUEST_TIMEOUT = 20.0

CFPB_API_URL = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
COURT_LISTENER_SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"
FTC_CONSUMER_FEED_URL = "https://www.ftc.gov/feeds/press-release-consumer-protection.xml"

SKU_RE = re.compile(r"\b[A-Z]{2,5}-\d{2,6}\b")
FEE_TERMS = ("late fee", "hidden fee", "setup fee", "activation fee", "annual fee")


@dataclass(frozen=True)
class Violation:
    id: str
    program: str
    source: str
    status: str
    window_start: date
    window_end: date
    claim_type: str
    rules: tuple[dict, ...] = field(default_factory=tuple)
    description: str = ""


class Source(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    def fetch(self) -> list[Violation]:
        ...


def _load_records() -> list[dict]:
    with (DATA_DIR / "sample_violations.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def _parse(record: dict) -> Violation:
    return Violation(
        id=record["id"],
        program=record["program"],
        source=record["source"],
        status=record.get("status", "open"),
        window_start=date.fromisoformat(record["window_start"]),
        window_end=date.fromisoformat(record["window_end"]),
        claim_type=record.get("claim_type", "complaint"),
        rules=tuple(record.get("rules", ())),
        description=record.get("description", ""),
    )


class FilteringSource(Source):
    def __init__(self, name: str) -> None:
        self.name = name

    def fetch(self) -> list[Violation]:
        return [_parse(r) for r in _load_records() if r["source"] == self.name]


class MockPACERSource(FilteringSource):
    def __init__(self) -> None:
        super().__init__("PACER")


class MockFTCSource(FilteringSource):
    def __init__(self) -> None:
        super().__init__("FTC")


def http_get(url: str, *, accept: str = "application/json") -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Encoding": "gzip",
        },
    )
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        body = response.read()
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            body = gzip.decompress(body)
    return body


def http_get_json(url: str) -> dict:
    return json.loads(http_get(url).decode("utf-8"))


def _parse_iso_date(value: str | None, fallback: date) -> date:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value[:19]).date()
    except ValueError:
        return fallback


def _parse_rfc822_datetime(value: str, fallback: date) -> date:
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError):
        return fallback


def derive_rules(*texts: str) -> tuple[dict, ...]:
    combined = " ".join(text for text in texts if text)
    lowered = combined.lower()
    rules: list[dict] = []
    for term in FEE_TERMS:
        if term in lowered:
            rules.append({"type": "overcharge", "fee_description": term, "threshold": 25.0})
            break
    markers = ("auto-renew", "auto renew", "auto-enroll", "auto enroll")
    if any(marker in lowered for marker in markers):
        rules.append({"type": "auto_enroll"})
    skus = sorted(set(SKU_RE.findall(combined)))
    if skus:
        rules.append({"type": "recall", "recall_skus": skus})
    return tuple(rules)


class CfpbSource(Source):
    name = "CFPB"

    def __init__(self, *, query: str = "auto-renew", size: int = 20) -> None:
        self.query = query
        self.size = size

    def fetch(self) -> list[Violation]:
        params = urllib.parse.urlencode({"q": self.query, "size": self.size})
        payload = http_get_json(f"{CFPB_API_URL}?{params}")
        hits = payload.get("hits", {}).get("hits", ())
        violations: list[Violation] = []
        for hit in hits:
            src = hit.get("_source") if isinstance(hit, dict) else {}
            complaint_id = src.get("complaint_id")
            if not complaint_id:
                continue
            texts = (
                src.get("product"),
                src.get("sub_product"),
                src.get("issue"),
                src.get("sub_issue"),
            )
            rules = derive_rules(*(t for t in texts if t))
            received = _parse_iso_date(src.get("date_received"), date.today())
            response = src.get("company_response") or ""
            company = src.get("company", "Unknown company")
            issue = src.get("issue", "consumer complaint")
            violations.append(
                Violation(
                    id=f"cfpb-{complaint_id}",
                    program=f"{company}: {issue}",
                    source=self.name,
                    status="closed" if response.lower().startswith("closed") else "open",
                    window_start=received - timedelta(days=365),
                    window_end=received,
                    claim_type="complaint",
                    rules=rules,
                    description=f"CFPB complaint {complaint_id} received {received.isoformat()}",
                )
            )
        return violations


class RecapSource(Source):
    name = "RECAP"

    def __init__(self, *, query: str = '"auto renew" class action', rows: int = 10) -> None:
        self.query = query
        self.rows = rows

    def fetch(self) -> list[Violation]:
        params = urllib.parse.urlencode({"type": "r", "q": self.query})
        payload = http_get_json(f"{COURT_LISTENER_SEARCH_URL}?{params}")
        today = date.today()
        violations: list[Violation] = []
        for item in payload.get("results", ())[: self.rows]:
            docket_id = item.get("docket_id")
            if not docket_id:
                continue
            doc_texts = [
                doc.get("short_description", "")
                for doc in item.get("recap_documents", ())
                if isinstance(doc, dict)
            ][:10]
            texts = [item.get("caseName", ""), *item.get("party", ()), *doc_texts]
            rules = derive_rules(*(t for t in texts if t))
            lowered = " ".join(texts).lower()
            is_class = "class action" in lowered or "class-wide" in lowered
            has_recall = any(rule["type"] == "recall" for rule in rules)
            filed = _parse_iso_date(item.get("dateFiled"), today)
            terminated = _parse_iso_date(item.get("dateTerminated"), None)
            case_name = item.get("caseName", "Unknown case")
            docket_number = item.get("docketNumber", "")
            court = item.get("court", "")
            violations.append(
                Violation(
                    id=f"recap-{docket_id}",
                    program=f"{case_name} ({docket_number}, {court})",
                    source=self.name,
                    status="closed" if terminated else "open",
                    window_start=filed,
                    window_end=terminated or today,
                    claim_type="class_claim" if (has_recall or is_class) else "complaint",
                    rules=rules,
                    description=f"RECAP docket {docket_number} filed {filed.isoformat()}",
                )
            )
        return violations


class FtcSource(Source):
    name = "FTC"

    def __init__(self, *, feed_url: str = FTC_CONSUMER_FEED_URL, limit: int = 15) -> None:
        self.feed_url = feed_url
        self.limit = limit

    def fetch(self) -> list[Violation]:
        body = http_get(self.feed_url, accept="application/rss+xml, application/xml")
        root = ET.fromstring(body)
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else []
        violations: list[Violation] = []
        for item in items[: self.limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            published = _parse_rfc822_datetime(pub_date, date.today())
            description = (item.findtext("description") or "").strip()
            if not title:
                continue
            rules = derive_rules(title, description)
            has_overcharge = any(rule["type"] == "overcharge" for rule in rules)
            digest = hashlib.sha256(link.encode("utf-8")).hexdigest()[:12]
            violations.append(
                Violation(
                    id=f"ftc-{digest}",
                    program=title,
                    source=self.name,
                    status="open",
                    window_start=published - timedelta(days=730),
                    window_end=published,
                    claim_type="class_claim" if has_overcharge else "complaint",
                    rules=rules,
                    description=link,
                )
            )
        return violations


def build_live_sources(name: str, query: str | None, limit: int) -> list[Source]:
    sources: list[Source] = []
    if name in ("cfpb", "all"):
        sources.append(CfpbSource(query=query or "auto-renew", size=limit))
    if name in ("recap", "all"):
        sources.append(RecapSource(query=query or '"auto renew" class action', rows=limit))
    if name in ("ftc", "all"):
        sources.append(FtcSource(limit=limit))
    return sources


def collect(sources: list[Source], rate_limit_seconds: float = 0.0) -> list[Violation]:
    found: list[Violation] = []
    for position, source in enumerate(sources):
        if position and rate_limit_seconds:
            time.sleep(rate_limit_seconds)
        try:
            found.extend(source.fetch())
        except (OSError, ValueError, SyntaxError, KeyError, TypeError) as exc:
            print(f"[prose] source {source.name} failed: {exc}", file=sys.stderr)
    return found