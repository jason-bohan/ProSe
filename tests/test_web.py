from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import date

import pytest

import prose.web as web
from prose import NOT_LEGAL_ADVICE
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
        assert "Claims overview" in page
        assert "barrow" in page

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


DOC_TEXT = (
    "Plaintiff: Janet A. Doe\nDefendant: Voltmax Direct LLC\n"
    "Filed: 2026-09-12\ncharged a hidden late fee of $30.00; class action settlement."
)


def test_document_ingest_and_tags() -> None:
    with _site() as site:
        form = urllib.parse.urlencode({"name": "Contract p.1", "text": DOC_TEXT}).encode()
        req = urllib.request.Request(site.url + "/documents", data=form, method="POST")
        with urllib.request.urlopen(req) as resp:
            page = resp.read().decode("utf-8")
        assert "Contract p.1" in page

        with urllib.request.urlopen(site.url + "/documents.json") as resp:
            payload = json.load(resp)
        doc = payload["documents"][0]
        assert doc["doc_id"] == "PROSE-000001"
        assert doc["name"] == "Contract p.1"
        assert "2026-09-12" in doc["tags"]["dates"]
        assert "$30.00" in doc["tags"]["amounts"]
        assert doc["tags"]["is_class_action"] is True
        assert "class action" in doc["tags"]["keywords"]


def test_document_post_requires_text() -> None:
    with _site() as site:
        form = urllib.parse.urlencode({"name": "empty", "text": "   "}).encode()
        req = urllib.request.Request(
            site.url + "/documents",
            data=form,
            method="POST",
            headers={"Accept": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 400


def test_document_post_blank_text_redirects_with_banner() -> None:
    with _site() as site:
        form = urllib.parse.urlencode({"name": "empty", "text": "   "}).encode()
        req = urllib.request.Request(site.url + "/documents", data=form, method="POST")
        with urllib.request.urlopen(req) as resp:
            page = resp.read().decode("utf-8")
        assert "nothing was added" in page


def _post_doc(site, name: str, text: str) -> None:
    form = urllib.parse.urlencode({"name": name, "text": text}).encode()
    req = urllib.request.Request(site.url + "/documents", data=form, method="POST")
    urllib.request.urlopen(req).read()


def test_discovery_page_filter_bates_and_graph() -> None:
    with _site() as site:
        _post_doc(
            site,
            "Complaint",
            DOC_TEXT + "\nSee [[Contract p.1]] and [[missing note]].",
        )
        _post_doc(site, "Contract p.1", "terms [[Complaint]]")

        with urllib.request.urlopen(site.url + "/documents") as resp:
            page = resp.read().decode("utf-8")
        assert "Discovery" in page
        assert "PROSE-000001" in page and "PROSE-000002" in page
        assert "in review set" in page
        assert "Recall" in page
        assert "window.GRAPH" in page
        assert "<a href=\"#PROSE-000002\">Contract p.1</a>" in page
        assert "[[missing note]]" in page
        assert "1 linked" in page

        with urllib.request.urlopen(site.url + "/graph.json") as resp:
            graph = json.load(resp)
        assert len(graph["nodes"]) == 3
        resolved = [e for e in graph["edges"] if e["r"]]
        assert len(resolved) == 2
        assert graph["backlinks"]["PROSE-000001"] == ["PROSE-000002"]
        assert graph["backlinks"]["PROSE-000002"] == ["PROSE-000001"]


def test_sample_review_set_builds_full_graph() -> None:
    with _site() as site:
        with urllib.request.urlopen(site.url + "/documents") as resp:
            empty_page = resp.read().decode("utf-8")
        assert "load example review set" in empty_page

        req = urllib.request.Request(
            site.url + "/documents/sample", data=b"", method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            page = resp.read().decode("utf-8")
        assert "PROSE-000001" in page and "PROSE-000003" in page
        assert "Issues in the review set" in page
        assert "load example review set" not in page

        with urllib.request.urlopen(site.url + "/graph.json") as resp:
            graph = json.load(resp)
        assert len(graph["nodes"]) == 5
        assert sum(1 for edge in graph["edges"] if edge["r"]) == 4
        assert graph["backlinks"]["PROSE-000001"] == [
            "PROSE-000002",
            "PROSE-000003",
        ]
        ca = [n for n in graph["nodes"] if n["id"] == "PROSE-000001"]
        assert ca and ca[0]["ca"] is True
        assert "window.DOCS" in page
        assert 'id="modal"' in page


def test_auto_enroll_matches(monkeypatch) -> None:
    monkeypatch.setattr(
        web, "collect", lambda s, rate_limit_seconds=0.0: [_class_violation()]
    )
    with _site() as site:
        body = urllib.parse.urlencode({"query": "auto renew", "limit": "5"}).encode()
        req = urllib.request.Request(
            site.url + "/suits/auto-join", data=body, method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            page = resp.read().decode("utf-8")
        assert "auto-enrolled" in page
        assert "1 suit(s) auto-enrolled" in page

        with urllib.request.urlopen(site.url + "/joins.json") as resp:
            joins = json.load(resp)
        entry = joins["joins"][0]
        assert entry["auto"] is True
        assert entry["file_by"] == "2026-06-01"
        assert entry["confidence"] == 0.8

        with urllib.request.urlopen(site.url + "/suits") as resp:
            page2 = resp.read().decode("utf-8")
        assert "file by 2026-06-01" in page2
        assert "auto-enroll matches" in page2


def test_exports_page() -> None:
    with _site() as site:
        with urllib.request.urlopen(site.url + "/exports") as resp:
            page = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "Exports" in page
        assert "case file" in page
        assert "download=\"case-file.json\"" in page
        assert "href=\"/api/simulate\"" in page
        assert "href=\"/exports/case-file\"" in page
        assert "href=\"/documents\">open</a>" in page
        assert "show formatted json" in page
        assert "review set" in page and "joinders" in page

        with urllib.request.urlopen(site.url + "/exports/case-file") as resp:
            viewer = resp.read().decode("utf-8")
        assert resp.status == 200
        assert "Matched claims" in viewer
        assert "Case timeline" in viewer
        assert "Hearing prep" in viewer
        assert "DRAFT - NOT LEGAL ADVICE" in viewer


def test_import_folder_dedupe_and_bad_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(web, "collect", lambda s, rate_limit_seconds=0.0: [])
    (tmp_path / "objections.txt").write_text(
        "objection: hearsay. See [[deposition of Jane]]", encoding="utf-8"
    )
    (tmp_path / "answers.json").write_text("{\"admits\": [1, 2]}", encoding="utf-8")
    (tmp_path / "skip.bin").write_bytes(b"\x00\x01\x02")
    body = urllib.parse.urlencode({"path": str(tmp_path)}).encode()
    with _site() as site:
        req = urllib.request.Request(site.url + "/import", data=body, method="POST")
        with urllib.request.urlopen(req) as resp:
            page = resp.read().decode("utf-8")
        assert "2 case file(s) into the review set" in page
        with urllib.request.urlopen(site.url + "/documents") as resp:
            docs = resp.read().decode("utf-8")
        assert "objections" in docs and "answers" in docs
        assert "[[deposition of Jane]]" in docs or "deposition of Jane" in docs

        req2 = urllib.request.Request(site.url + "/import", data=body, method="POST")
        with urllib.request.urlopen(req2) as resp2:
            page2 = resp2.read().decode("utf-8")
        assert "0 case file(s) into the review set" in page2
        assert "2 skipped as duplicates" in page2

        bad = urllib.parse.urlencode({"path": str(tmp_path / "nope")}).encode()
        req3 = urllib.request.Request(site.url + "/import", data=bad, method="POST")
        with urllib.request.urlopen(req3) as resp3:
            page3 = resp3.read().decode("utf-8")
        assert "import failed" in page3
        assert "no such path" in page3

        with urllib.request.urlopen(site.url + "/live") as resp:
            live = resp.read().decode("utf-8")
        assert "Load case files (SD card / folder / zip)" in live
        assert "action=\"/import\"" in live


def test_recall_search() -> None:
    with _site() as site:
        _post_doc(site, "Contract p.1", DOC_TEXT)
        with urllib.request.urlopen(site.url + "/recall?q=late+fee") as resp:
            data = json.load(resp)
        assert data["documents"][0]["doc_id"] == "PROSE-000001"
        assert "late fee" in data["documents"][0]["snippet"]

        with urllib.request.urlopen(site.url + "/recall") as resp:
            everything = json.load(resp)
        assert len(everything["documents"]) == 1
        assert len(everything["violations"]) == 3


def _class_violation() -> Violation:
    return Violation(
        id="recap-42",
        program="Smith v. Acme Subscriptions, Inc. (1:26-cv-1, D. Mass.)",
        source="RECAP",
        status="open",
        window_start=date(2026, 1, 1),
        window_end=date(2026, 6, 1),
        claim_type="class_claim",
        rules=({"type": "auto_enroll"},),
        description="class action over auto-renewal",
    )


def test_suits_discovery_and_join(monkeypatch) -> None:
    monkeypatch.setattr(web, "collect", lambda s, rate_limit_seconds=0.0: [_class_violation()])
    with _site() as site:
        with urllib.request.urlopen(site.url + "/suits?query=auto+renew&limit=5") as resp:
            page = resp.read().decode("utf-8")
        assert "Smith v. Acme" in page
        assert "matches your record" in page

        payload = urllib.parse.urlencode(
            {
                "violation": html.escape(
                    json.dumps(web.violation_to_json(_class_violation())), quote=True
                )
            }
        ).encode()
        req = urllib.request.Request(site.url + "/suits/join", data=payload, method="POST")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200

        with urllib.request.urlopen(site.url + "/joins.json") as resp:
            joins = json.load(resp)
        entry = joins["joins"][0]
        assert entry["violation_id"] == "recap-42"
        assert entry["status"] == "draft_ready"
        assert entry["matched"] is True
        assert entry["confidence"] == 0.8
        assert NOT_LEGAL_ADVICE in entry["draft"]

        with urllib.request.urlopen(site.url + "/suits") as resp:
            page2 = resp.read().decode("utf-8")
        assert "joined" in page2.lower()

        with urllib.request.urlopen(site.url + "/suits.json") as resp:
            data = json.load(resp)
        assert data["suits"][0]["match"]["confidence"] == 0.8


def test_join_rejects_missing_payload() -> None:
    with _site() as site:
        req = urllib.request.Request(
            site.url + "/suits/join", data=b"violation=", method="POST"
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req)
        assert exc.value.code == 400


def test_page_shell_consistency() -> None:
    """Every page shares the shell: lang, viewport, branded title, nav state,
    and the not-legal-advice disclaimer."""
    pages = ("/", "/copilot", "/practice", "/documents", "/live",
             "/exports", "/vocabulary", "/research", "/suits", "/controller")
    with _site() as site:
        for path in pages:
            # "/" cold-starts the pipeline on a fresh site, so allow for it.
            # 30s: cold start varies with machine load (AV scans, etc.).
            with urllib.request.urlopen(site.url + path, timeout=30) as resp:
                page = resp.read().decode("utf-8")
            assert 'lang="en"' in page, path
            assert 'name="viewport"' in page, path
            title = re.search(r"<title>(.*?)</title>", page)
            assert title and title.group(1).endswith(" · LexGlasses"), path
            assert "legal advice" in page.lower(), path
            assert "<nav" in page, path
            assert 'class="skip" href="#main"' in page, path
            assert '<main id="main"' in page, path
            assert f'<a href="{path}" aria-current="page"' in page, path
            # Heading hierarchy starts at h1 and never skips a level.
            levels = [int(m) for m in re.findall(r"<h([123])[^>]*>", page)]
            assert levels and levels[0] == 1, path
            assert all(b <= a + 1
                       for a, b in zip(levels, levels[1:], strict=False)), path


def test_voice_controls_are_wired() -> None:
    """Voice selects exist in every speech-capable page, share one persisted
    key, and the chosen voice reaches synthesis and dictation."""
    pages = ("/", "/copilot", "/practice", "/documents", "/live",
             "/exports", "/vocabulary", "/research", "/suits", "/controller")
    body_by_path, scripts_by_path = {}, {}
    with _site() as site:
        for path in pages:
            with urllib.request.urlopen(site.url + path, timeout=30) as resp:
                body = resp.read().decode("utf-8")
            body_by_path[path] = body
            scripts_by_path[path] = "\n".join(
                re.findall(r"<script>(.*?)</script>", body, re.S))
    # Every element the scripts reach for must exist in the served page,
    # or the handler that touches it dies with a TypeError.
    for path in pages:
        wanted = set(re.findall(r"\$\('([^']+)'\)", scripts_by_path[path]))
        present = set(re.findall(r'id="([^"]+)"', body_by_path[path]))
        assert wanted <= present, f"{path}: {sorted(wanted - present)}"
    assert 'id="practice-voice"' in body_by_path["/practice"]
    assert 'id="hud-voice"' in body_by_path["/controller"]
    assert 'id="copilot-voice"' in body_by_path["/copilot"]
    # One persisted voice key everywhere; legacy keys still load as fallback.
    for path in ("/controller", "/practice", "/copilot", "/vocabulary"):
        assert "prose-voice" in scripts_by_path[path], path
    for path in ("/controller", "/practice", "/copilot"):
        script = scripts_by_path[path]
        assert "voiceschanged', refreshVoices" in script, path
        assert ".voice = voice" in script, path
        assert "voice.lang : 'en-US'" in script, path
    assert "'hear-coach').addEventListener('click'" in scripts_by_path["/practice"]
    assert "'hear-cue').addEventListener('click'" in scripts_by_path["/copilot"]
    assert "speech.voice" in scripts_by_path["/vocabulary"]
    # SpeechRecognition has no .voice property; language is the real channel.
    for path in ("/controller", "/copilot"):
        assert "rec.voice" not in scripts_by_path[path], path


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_page_scripts_parse(tmp_path) -> None:
    """Every inline <script> on every page must parse. One SyntaxError kills
    the whole script, silently turning an interactive page into static HTML."""
    pages = ("/", "/copilot", "/practice", "/documents", "/live",
             "/exports", "/vocabulary", "/research", "/suits", "/controller")
    checked = 0
    with_scripts = set()
    with _site() as site:
        for path in pages:
            with urllib.request.urlopen(site.url + path, timeout=30) as resp:
                body = resp.read().decode("utf-8")
            sources = re.findall(r"<script>(.*?)</script>", body, re.S)
            if sources:
                with_scripts.add(path)
            for index, source in enumerate(sources):
                target = (tmp_path
                          / f"{path.strip('/').replace('/', '_') or 'home'}-{index}.js")
                target.write_text(source, encoding="utf-8")
                result = subprocess.run(["node", "--check", str(target)],
                                        capture_output=True, text=True)
                assert result.returncode == 0, (
                    f"{path} script #{index}: {result.stdout}{result.stderr}")
                checked += 1
    # /live, /exports and /suits are server-rendered with no inline script;
    # the two voice pages must have been found and parsed.
    assert checked >= 9, checked
    assert {"/practice", "/controller"} <= with_scripts, with_scripts