from __future__ import annotations

import html
import json
import sys
import threading
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .crawler import Violation, build_live_sources, collect
from .device import frame_to_payload
from .hud import HudSimulator
from .matcher import MatchResult
from .pipeline import MIN_AUTO_CONFIDENCE, SAMPLE_TRANSCRIPT, PipelineResult, run


def violation_to_json(violation: Violation) -> dict:
    item = asdict(violation)
    item["window_start"] = violation.window_start.isoformat()
    item["window_end"] = violation.window_end.isoformat()
    return item


def match_to_json(match: MatchResult) -> dict:
    v = match.violation
    return {
        "violation_id": v.id,
        "program": v.program,
        "source": v.source,
        "claim_type": match.claim_type,
        "confidence": round(match.confidence, 3),
        "evidence": list(match.evidence),
    }


def simulate_result_json(result: PipelineResult) -> dict:
    case = None
    if result.case is not None:
        case = {
            "case_number": result.case.case_number,
            "cause": result.case.cause,
            "party": result.case.party,
            "stage": result.case.stage,
            "history": [{"day": day, "entry": entry} for day, entry in result.case.history],
        }
    briefing = None
    if result.briefing is not None:
        briefing = {
            "stage": result.briefing.stage,
            "title": result.briefing.title,
            "checklist": list(result.briefing.checklist),
            "caution": result.briefing.caution,
        }
    return {
        "total_violations": result.total_violations,
        "min_auto_confidence": MIN_AUTO_CONFIDENCE,
        "matches": [match_to_json(m) for m in result.matches],
        "review": [match_to_json(m) for m in result.review],
        "case": case,
        "briefing": briefing,
        "tags": result.tags.summary().splitlines() if result.tags is not None else [],
        "drafts": [
            {"violation_id": vid, "doc_type": d.doc_type, "document_id": d.document_id, "text": d.text}
            for vid, d in result.drafts
        ],
        "frames": [frame_to_payload(f) for f in result.frames],
    }


PAGE_CSS = """
body{font-family:system-ui,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}
a{color:#60a5fa}code,pre{background:#1e293b;padding:.2em .4em;border-radius:4px;font-family:ui-monospace,monospace}
.container{max-width:1100px;margin:0 auto;padding:1.5rem}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:1.5rem}
.badge{background:#1e3a5f;color:#93c5fd;padding:.2rem .6rem;border-radius:999px;font-size:.85rem}
.card{background:#111827;border:1px solid #1f2937;border-radius:8px;padding:1rem;margin-bottom:1rem}
.card h3{margin:0 0 .5rem;font-size:1.1rem;color:#fde047}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:.75rem;margin-bottom:1rem}
.stat{background:#1e293b;border-radius:6px;padding:.75rem;text-align:center}
.stat .n{font-size:2rem;font-weight:700;color:#fde047}.stat .l{font-size:.85rem;color:#94a3b8}
table{width:100%;border-collapse:collapse;font-size:.9rem}
th,td{text-align:left;padding:.5rem .75rem;border-bottom:1px solid #334155}
th{color:#94a3b8;font-weight:600;background:#0f172a}
tr:hover td{background:#1e293b}
.chip{display:inline-block;background:#1e3a5f;color:#93c5fd;padding:.1rem .4rem;border-radius:4px;font-size:.75rem;margin:.1rem}
.warning{background:#451a03;color:#fbbf24;border-left:3px solid #f59e0b;padding:.75rem;margin:.5rem 0;border-radius:4px}
details{margin:.5rem 0}details>summary{cursor:pointer;color:#fde047}
pre{white-space:pre-wrap;word-break:break-word}
.hud{background:#020617;border:1px solid #1e3a5f;border-radius:6px;padding:1rem;min-height:200px;font-family:ui-monospace,monospace;font-size:.85rem;line-height:1.6}
.hud .seq{color:#64748b}.hud .spk{color:#fde047}.hud .txt{color:#e2e8f0}
.hud .obj{color:#f87171;margin-left:1rem}.hud .prm{color:#34d399;margin-left:1rem}
footer{text-align:center;color:#64748b;font-size:.8rem;margin-top:2rem;padding-top:1rem;border-top:1px solid #1e293b}
"""


HUD_JS = r"""
function connectHud() {
  var es = new EventSource("/hud/stream");
  var box = document.getElementById("hud");
  es.addEventListener("frame", function (e) {
    var f = JSON.parse(e.data);
    var div = document.createElement("div");
    div.innerHTML = '<span class="seq">#' + f.seq + '</span> ' +
      '<span class="spk">' + htmlEscape(f.speaker) + ':</span> ' +
      '<span class="txt">' + htmlEscape(f.transcript) + '</span>';
    if (f.objections && f.objections.length) {
      f.objections.forEach(function (o) {
        var od = document.createElement("div");
        od.className = "obj";
        od.textContent = "  OBJECTION " + o.label + " (" + o.citation + ") conf=" + o.confidence.toFixed(2);
        div.appendChild(od);
      });
    }
    if (f.prompt) {
      var pd = document.createElement("div");
      pd.className = "prm";
      pd.textContent = "  HUD PROMPT> " + f.prompt;
      div.appendChild(pd);
    }
    box.appendChild(div);
    if (box.children.length > 20) box.removeChild(box.firstChild);
    box.scrollTop = box.scrollHeight;
  });
  es.onerror = function () {
    es.close();
    setTimeout(connectHud, 800);
  };
}
function htmlEscape(s) {
  var m = {"&": "&", "<": "<", ">": ">", "\"": "\"", "'": "&#039;"};
  return s.replace(/[&<>"']/g, function (c) { return m[c]; });
}
document.addEventListener("DOMContentLoaded", connectHud);
"""


def render_dashboard(result: PipelineResult) -> str:
    e = html.escape
    parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><title>LexGlasses Dashboard</title>",
        f"<style>{PAGE_CSS}</style>",
        f"<script>{HUD_JS}</script>",
        "</head><body>",
        "<div class=\"container\">",
        "<header class=\"header\">",
        "<div><h1>LexGlasses</h1><div class=\"badge\">Project JusticeStack \u2014 simulation, not legal advice</div></div>",
        "<nav><a href=\"/api/simulate\">JSON API</a> \u00b7 <a href=\"/live\">Live ingest</a></nav>",
        "</header>",
        "<section class=\"card stats\">",
        f"<div class=\"stat\"><div class=\"n\">{result.total_violations}</div><div class=\"l\">violations crawled</div></div>",
        f"<div class=\"stat\"><div class=\"n\">{len(result.matches)}</div><div class=\"l\">auto matches (\u2265 {MIN_AUTO_CONFIDENCE:.2f})</div></div>",
        f"<div class=\"stat\"><div class=\"n\">{len(result.review)}</div><div class=\"l\">human review</div></div>",
        f"<div class=\"stat\"><div class=\"n\">{len(result.drafts)}</div><div class=\"l\">draft documents</div></div>",
        "</section>",
    ]

    if result.matches:
        parts.append("<section class=\"card\"><h3>Auto Matches</h3><table>")
        parts.append("<tr><th>Violation ID</th><th>Program</th><th>Source</th><th>Claim</th><th>Confidence</th></tr>")
        for m in result.matches:
            v = m.violation
            parts.append(
                f"<tr><td><code>{e(v.id)}</code></td><td>{e(v.program)}</td>"
                f"<td>{e(v.source)}</td><td>{e(m.claim_type)}</td>"
                f"<td>{m.confidence:.2f}</td></tr>"
            )
        parts.append("</table></section>")

    if result.review:
        parts.append("<section class=\"card\"><h3>Held for Human Review</h3>")
        for m in result.review:
            v = m.violation
            parts.append(
                f"<div class=\"warning\"><strong>{e(v.id)}</strong> \u2014 {e(v.program)} "
                f"(confidence {m.confidence:.2f} < {MIN_AUTO_CONFIDENCE:.2f})"
            )
            for ev in m.evidence:
                parts.append(f"<div style=\"margin-left:1rem\">{e(ev)}</div>")
            parts.append("  \u2192 no document auto-generated; verify manually before acting</div>")
        parts.append("</section>")

    if result.case is not None:
        c = result.case
        parts.append(f"<section class=\"card\"><h3>Case {e(c.case_number)} \u2014 {e(c.cause)}</h3>")
        parts.append(f"<p>Current stage: <strong>{e(c.stage)}</strong></p>")
        parts.append("<ul>")
        for day, entry in c.history:
            parts.append(f"<li><code>{e(day)}</code> \u2014 {e(entry)}</li>")
        parts.append("</ul></section>")

    if result.briefing is not None:
        b = result.briefing
        parts.append(f"<section class=\"card\"><h3>Stage Briefing: {e(b.stage)} \u2014 {e(b.title)}</h3>")
        parts.append("<ul>")
        for item in b.checklist:
            parts.append(f"<li>[ ] {e(item)}</li>")
        parts.append(f"</ul><p class=\"warning\">{e(b.caution)}</p></section>")

    if result.tags is not None:
        parts.append("<section class=\"card\"><h3>Entity Tags</h3><pre>")
        for line in result.tags.summary().splitlines():
            parts.append(e(line))
        parts.append("</pre></section>")

    if result.drafts:
        parts.append("<section class=\"card\"><h3>Draft Documents</h3>")
        for vid, d in result.drafts:
            parts.append(
                f"<details><summary>[<code>{e(vid)}</code>] {e(d.doc_type)} \u2192 {e(d.document_id)}</summary>"
                f"<pre>{e(d.text)}</pre></details>"
            )
        parts.append("</section>")

    parts.append("<section class=\"card\"><h3>Glasses HUD \u2014 Live Stream (SSE)</h3>")
    parts.append("<div id=\"hud\" class=\"hud\"></div></section>")

    parts.append("<footer>DISCLAIMER: simulation output only. Not legal advice; not for filing.</footer>")
    parts.append("</div></body></html>")
    return "\n".join(parts)


def render_live_page(
    source: str, query: str | None, limit: int, violations: list[Violation]
) -> str:
    e = html.escape
    mdash = "\u2014"
    parts = [
        "<!doctype html>",
        "<html><head><meta charset=\"utf-8\"><title>Live Ingest</title>",
        f"<style>{PAGE_CSS}</style>",
        "</head><body>",
        "<div class=\"container\">",
        "<header class=\"header\">",
        "<div><h1>Live Ingest</h1><div class=\"badge\">Real public sources (CFPB, RECAP, FTC)</div></div>",
        "<nav><a href=\"/\">Dashboard</a> \u00b7 <a href=\"/api/simulate\">JSON API</a></nav>",
        "</header>",
        f"<section class=\"card\"><p>Source: <strong>{e(source)}</strong> "
        f"{mdash + ' query: ' + e(query) if query else ''} {mdash} limit: {limit}</p>",
        f"<p>Fetched <strong>{len(violations)}</strong> violation(s).</p></section>",
    ]
    if violations:
        parts.append("<section class=\"card\"><h3>Violations</h3>")
        for v in violations:
            rules = ", ".join(r["type"] for r in v.rules) or "none"
            parts.append(
                f"<details><summary>[<code>{e(v.source)}</code>] {e(v.id)} {mdash} {e(v.program)} "
                f"(<span class=\"chip\">{e(v.status)}</span>) rules: {e(rules)}</summary>"
                f"<pre>{e(v.description)}</pre></details>"
            )
        parts.append("</section>")
    else:
        parts.append("<section class=\"card\"><p>No violations matched for these parameters.</p></section>")

    parts.append("<footer>DISCLAIMER: live data from public APIs. Not legal advice.</footer>")
    parts.append("</div></body></html>")
    return "\n".join(parts)


def _clamp_limit(text: str, default: int = 10) -> int:
    try:
        val = int(text)
        return max(1, min(50, val))
    except (ValueError, TypeError):
        return default


def _live_params(params: dict[str, list[str]]) -> tuple[str, str | None, int]:
    source = params.get("source", ["all"])[0]
    if source not in ("cfpb", "recap", "ftc", "all"):
        source = "all"
    query = params.get("query", [None])[0]
    limit = _clamp_limit(params.get("limit", ["10"])[0])
    return source, query, limit


class WebApp:
    def __init__(self, live_ttl_seconds: float = 30.0) -> None:
        self.live_ttl_seconds = live_ttl_seconds
        self._lock = threading.Lock()
        self._simulate: PipelineResult | None = None
        self._runs = 0
        self._live: dict[tuple[str, str, int], tuple[float, list[Violation]]] = {}

    def simulate(self) -> PipelineResult:
        with self._lock:
            if self._simulate is None:
                self._simulate = run()
                self._runs += 1
            return self._simulate

    def live(self, source: str, query: str | None, limit: int) -> list[Violation]:
        key = (source, query or "", limit)
        with self._lock:
            hit = self._live.get(key)
            if hit is not None and time.monotonic() - hit[0] < self.live_ttl_seconds:
                return hit[1]
        violations = collect(build_live_sources(source, query, limit), rate_limit_seconds=1.0)
        with self._lock:
            self._live[key] = (time.monotonic(), violations)
        return violations


class ProseHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    app: WebApp

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _html(self, status: int, text: str) -> None:
        self._send(status, text.encode("utf-8"), "text/html; charset=utf-8")

    def _json(self, status: int, payload: dict | list) -> None:
        self._send(status, (json.dumps(payload, indent=2) + "\n").encode("utf-8"), "application/json")

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[prose.web] {self.address_string()} {fmt % args}", file=sys.stderr)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._html(200, render_dashboard(self.app.simulate()))
            elif path == "/live":
                source, query, limit = _live_params(params)
                self._html(200, render_live_page(source, query, limit, self.app.live(source, query, limit)))
            elif path == "/api/simulate":
                self._json(200, simulate_result_json(self.app.simulate()))
            elif path == "/live.json":
                source, query, limit = _live_params(params)
                violations = self.app.live(source, query, limit)
                self._json(
                    200,
                    {
                        "source": source,
                        "query": query,
                        "limit": limit,
                        "violations": [violation_to_json(v) for v in violations],
                    },
                )
            elif path == "/hud/stream":
                self._sse()
            else:
                self._send(404, b'{"error": "not found"}\n', "application/json")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        hud = HudSimulator()
        for line in SAMPLE_TRANSCRIPT:
            frame = hud.feed(line)
            payload = json.dumps(frame_to_payload(frame))
            try:
                self.wfile.write(f"event: frame\ndata: {payload}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return
            time.sleep(0.8)


@dataclass
class WebSite:
    server: ThreadingHTTPServer
    app: WebApp

    @property
    def url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.server.serve_forever()


def build_site(host: str, port: int, app: WebApp | None = None) -> WebSite:
    app = app or WebApp()

    class _Handler(ProseHandler):
        pass

    _Handler.app = app

    class _Server(ThreadingHTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    server = _Server((host, port), _Handler)
    return WebSite(server, app)


def serve(host: str = "127.0.0.1", port: int = 8000, block: bool = True) -> WebSite:
    site = build_site(host, port)
    print(f"[prose.web] dashboard  : {site.url}")
    print(f"[prose.web] live ingest: {site.url}/live")
    print(f"[prose.web] HUD stream : {site.url}/hud/stream (SSE)")
    print(f"[prose.web] api        : {site.url}/api/simulate, {site.url}/live.json")
    if block:
        site.start()
    return site