from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import date

import prose.web as web
from prose.crawler import Violation
from prose.web import build_site


@contextmanager
def _site():
    site = build_site("127.0.0.1", 0)
    thread = threading.Thread(target=site.server.serve_forever, daemon=True)
    thread.start()
    try:
        yield site
    finally:
        site.server.shutdown()
        site.server.server_close()
        thread.join(timeout=5)


def test_dashboard_and_cache() -> None:
    with _site() as site:
        base = site.url
        with urllib.request.urlopen(base + "/") as resp:
            assert resp.status == 200
            page = resp.read().decode("utf-8")
        assert "LexGlasses" in page
        assert "OBJECTION" in page or "objection" in page

        with urllib.request.urlopen(base + "/api/simulate") as resp:
            data = json.load(resp)
        assert data["total_violations"] == 3
        assert len(data["matches"]) == 2
        assert len(data["review"]) == 1
        assert len(data["drafts"]) == 2
        assert len(data["frames"]) == 5

        with urllib.request.urlopen(base + "/api/simulate") as resp:
            json.load(resp)
        assert site.app._runs == 1

        try:
            urllib.request.urlopen(base + "/nope")
            raise AssertionError("expected 404")
        except urllib.error.HTTPError as exc:
            assert exc.code == 404


def test_live_json_and_ttl_cache(monkeypatch) -> None:
    calls = []

    def fake_collect(sources, rate_limit_seconds=0.0):
        calls.append(1)
        return [
            Violation(
                id="cfpb-1",
                program="Acme: bad fee",
                source="CFPB",
                status="open",
                window_start=date(2026, 1, 1),
                window_end=date(2026, 2, 1),
                claim_type="complaint",
                rules=[],
                description="d",
            )
        ]

    monkeypatch.setattr(web, "collect", fake_collect)
    with _site() as site:
        for _ in range(2):
            with urllib.request.urlopen(site.url + "/live.json?source=cfpb&limit=2") as resp:
                data = json.load(resp)
            assert data["violations"][0]["id"] == "cfpb-1"
        assert len(calls) == 1


def test_sse_streams_frames() -> None:
    with _site() as site:
        req = urllib.request.urlopen(site.url + "/hud/stream", timeout=10)
        chunk = b""
        while b"\n\n" not in chunk:
            chunk += req.read1(1024)
        assert chunk.startswith(b"event: frame")
        data_line = chunk.split(b"\n\n")[0].split(b"\n", 1)[1]
        frame = json.loads(data_line.removeprefix(b"data: "))
        assert frame["seq"] == 1
        req.close()