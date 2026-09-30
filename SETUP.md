# Setup

## Environment

```
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux
pip install -e ".[dev]"       # pytest, ruff
python -m pytest              # test suite (includes emulation tests, see below)
python -m ruff check .        # lint / static analysis gate
```

That's the whole install. No Scrapy, Postman, WireMock, Jinja2, Faker, Android
Studio, or vendor SDKs are required — see "Intentionally not used" below for why.

## Web dashboard (fastest possible, zero deps)

```
prose serve          # http://127.0.0.1:8000  (or `python -m prose.cli serve`)
```

The server is a single stdlib `ThreadingHTTPServer` (`prose/web.py`) — no
framework, no build step, instant cold start. Performance tricks:

- **Pipeline runs once** and is cached in-process; every subsequent request
  (dashboard, `/api/simulate`, `/api/live.json`) serves the same pre-computed
  result with no re-crawl, no re-match, no re-render of documents.
- **Live ingest is cached** per `(source, query, limit)` with a 30-second TTL,
  so repeated page loads or API polls never hammer the public CFPB/RECAP/FTC
  endpoints (which rate-limit unauthenticated clients).
- **HUD stream is SSE** (`/hud/stream`) — one `EventSource` connection pushes
  scripted `HudFrame` objects from the `HudSimulator` with a small delay.
  Browser auto-reconnects on close; the feed loops indefinitely. No WebSocket
  handshake, no `websockets` package required.
- **Thread-per-request** via `ThreadingHTTPServer` (Python's built-in) is
  sufficient for the local-dev load profile; keep-alive is on (`HTTP/1.1`),
  every response sets `Content-Length` for pipelining.
- **All responses are CORS-open** (`Access-Control-Allow-Origin: *`) so a
  standalone HUD bridge page or `curl` works from any origin.

One optional extra, for the smart-glasses HUD link:

```
pip install ".[glasses]"      # websockets (ws= transport) + vosk (live streaming ASR)
```

Vosk also needs a downloaded acoustic model (e.g. `vosk-model-small-en-us-0.15`
from https://alphacephei.com/vosk/models) — point `prose.cli listen --model`
at the extracted directory. Without `[glasses]` installed, `ws=` transports and
`VoskTranscriber` both raise a clear `RuntimeError` when used; every other code
path (console/jsonl transports, `MockASR`, and the whole crawler/matcher/docs
pipeline) works with zero third-party dependencies.

## Live data-source notes

`prose ingest` hits real, keyless public endpoints:

- **CFPB** — Consumer Complaint Database v1 search API.
- **RECAP** (CourtListener) — docket search API, no API key required.
- **FTC** — consumer-protection press-release RSS feed.

All three degrade independently in `crawler.collect()` — a failing source is
logged to stderr and skipped, not fatal. `prose.cli simulate` never touches
the network (it uses `MockPACERSource`/`MockFTCSource` over
`prose/data/sample_violations.json`); only `prose.cli ingest` does live
fetches. Rate limits, CAPTCHAs, and schema drift on these feeds are the
responsibility of the `Source` adapters in `prose/crawler.py`.

## Intentionally not used

An earlier draft testing spec for this project listed a standard web-scraping/
mobile-dev toolchain (Scrapy, Postman, WireMock/Mockoon, Faker, Jinja2,
Android Studio + emulator, a smart-glasses vendor SDK, Audacity, SonarQube).
None of it is installed here, on purpose:

- **Scrapy** — the crawler is three small stdlib `urllib.request`/`xml.etree`
  adapters (`prose/crawler.py`), not a spidering job; a scraping framework
  would be net-negative weight for three fixed API endpoints.
- **Postman / WireMock / Mockoon** — replaced by
  `tests/emulation/mock_endpoints.py`, a ~100-line stdlib
  `http.server.ThreadingHTTPServer` that serves canned CFPB/RECAP/FTC
  responses (with real gzip, real headers, real timeouts) from inside the
  test process. No external process to start/stop, no app to install.
- **Faker** — replaced by `tests/emulation/synthetic.py`, a seeded
  `random.Random`-driven generator producing `Violation`/`UserRecord` graphs
  for fuzzing the matcher. Deterministic per seed, zero dependencies.
- **Jinja2** — `prose/docs.py` deliberately does plain `{{TOKEN}}` string
  substitution, not a template engine, so every draft is auditable
  token-for-token (see "Design for low-capability models" in README.md).
  Nothing for Jinja2 to test.
- **Android Studio / vendor smart-glasses SDK** — there's no glasses app in
  this repo to emulate; `prose/device.py` is a transport layer (console /
  JSONL / WebSocket) that any BLE- or USB-tethered companion app can consume.
  `tests/emulation/device_emulator.py` stands in for that companion app: a
  local `websockets` server that plays the "glasses" side of
  `WebSocketTransport`, so the serialize → socket → deserialize path is
  covered without hardware or an emulator download.
- **Audacity / heavier ASR SDKs (Whisper)** — the streaming ASR path is
  implemented with Vosk instead (`prose/asr.py::VoskTranscriber`; see "Real
  glasses link" in README.md and the `[glasses]` extra above): a small,
  offline, pure-Python-bindings engine, consistent with the "low-capability
  model in the hot path" design rather than a heavier cloud/Torch-based
  option. Its unit tests (`tests/test_asr.py`) use a `FakeTranscriber` test
  double to cover the session-wiring logic (buffering, finalize, frame
  sequencing) without needing the real model or an audio fixture — actual
  recognition accuracy isn't something a unit test can meaningfully assert
  anyway. Audacity itself still has no role: there's no audio *editing* need,
  only streaming PCM chunks through a recognizer.
- **SonarQube** — `ruff check .` (already a dev dependency) covers static
  analysis; `tests/test_compliance_emulation.py::test_ruff_static_analysis_passes`
  runs it as part of the test suite so lint regressions fail CI, not just a
  local, easy-to-skip manual step.

## Emulation testing

`tests/emulation/` holds the harness; the `tests/test_*_emulation.py` and
`tests/test_matcher_fuzz.py` files use it to exercise real code paths that the
unit tests (which monkeypatch at the function boundary) don't reach:

| File | Emulates | Exercises |
|---|---|---|
| `tests/test_crawler_emulation.py` | CFPB/RECAP/FTC HTTP endpoints | real gzip decode, headers, HTTP error codes, timeouts, malformed bodies, 404s |
| `tests/test_matcher_fuzz.py` | synthetic violation/user data | matcher invariants (confidence bounds, window/threshold/opt-out logic) over 500 randomized cases |
| `tests/test_hud_device_emulation.py` | smart-glasses companion app | the real `WebSocketTransport` over an actual socket, not an in-memory stream |
| `tests/test_asr.py` | a streaming ASR backend | `StreamingHudSession` buffering/finalize/frame-sequencing via a `FakeTranscriber`, plus `VoskTranscriber`'s missing-dependency error |
| `tests/test_compliance_emulation.py` | regulatory/compliance review | static-analysis gate + a claim-type × doc-type matrix scanned for outcome-guaranteeing language |

Run just this layer with `python -m pytest -k emulation`.
