# Setup

For the Scouting policy library and Google Drive ZIP import, see
[RESEARCH.md](RESEARCH.md). Install its optional PDF/HTML dependencies with
`python -m pip install -e ".[research]"`.

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
framework, no build step, instant cold start. Pages:

- `/` — dashboard: claim stats, matched claims vs review queue, case
  timeline, briefings, drafts, live transcript HUD panel
- `/documents` — **Discovery**: review set with Bates-style IDs
  (`PROSE-000001`), issue-code tags, client-side filter, `[[wikilink]]`
  graph with backlinks, and **Recall** keyword search across the review
  set and collected records (`/recall?q=`, `/graph.json`, `/documents.json`)
- `/suits` — class-action finder: searches RECAP dockets, matches suits
  against your record, one click **join** → drafts a joinder, or
  **auto-enroll matches** (confidence ≥ 0.75) → drafts them all with
  filing deadlines (`/joins.json`, `/suits.json`)
- `/live` — **Collections**: collect public ESI from CFPB/RECAP/FTC
  (`/live.json`), plus **Load case files** — point at a mounted SD card,
  folder, or `.zip` and every `.txt .md .json .jsonl .csv .pdf` is read
  (PDF text extracted, system/hidden folders skipped, duplicates dropped)
  into the review set (`POST /import`)
- `/exports` — productions page: download/open the case file, review set,
  graph, joinders, collected records, and recall as JSON; the case file
  opens as a readable viewer (`/exports/case-file`, `/api/simulate`)
- `/controller` — phone gamepad for the glasses: pick Debate or Litigation
  practice on the HUD launcher (`POST /api/hud/menu`), configure the session
  (topic, opponent, up to six case files), then drive the debate with send /
  suggestion / voice actions, an animated confidence meter, and coach
  rebuttals; paste the glasses stream link (`/hud/stream`) into the MemoMind
  relay once — menu, confidence, and cues follow automatically, and the
  relay itself adds a **controller** row (opens this page) plus an embedded
  **matrix** with the mode switch and both bipolar pads

Machines: `/api/simulate`, `/recall`, `/graph.json`, `/live.json`,
`/suits.json`, `/documents.json`, `/joins.json`. SSE: `/hud/stream`
(the glasses receive only these live frames, never the full exports).

Performance tricks:

- **Pipeline runs once** and is cached in-process; every subsequent request
  (dashboard, `/api/simulate`, `/api/live.json`) serves the same pre-computed
  result with no re-crawl, no re-match, no re-render of documents.
- **Live ingest is cached** per `(source, query, limit)` with a 30-second TTL,
  so repeated page loads or API polls never hammer the public CFPB/RECAP/FTC
  endpoints (which rate-limit unauthenticated clients).
- **HUD stream is SSE** (`/hud/stream`) — every connection subscribes to the
  live frame hub and immediately replays the current frame (the launcher menu
  when idle, the latest coach/practice cue during a session). Publishes come
  from HUD menu moves, practice turns (confidence + opponent mood scoring),
  and live-coach turns. Browser auto-reconnects on close. No WebSocket
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

## Live coach model configuration

### Choose the debate model, including your own Ollama host

The **AI model** menu on `/practice` lets you choose a model before starting or
switch between turns. Switching preserves the conversation, vocabulary focus words,
and text in the reply box. The same selected model handles the opponent and coach.
Existing coach text remains labeled with the model that wrote it; the new model
handles the next reply. Selection is remembered in this browser. There is no
automatic fallback that sends the conversation to a different provider.

ChatJimmy is a built-in option. The model configured through server environment
variables is also listed. To add Ollama hosts, create `.prose/ai-models.json`
(or `ai-models.json` under `PROSE_DATA_DIR`):

```json
{
  "version": 1,
  "default": "my-ollama",
  "profiles": [
    {
      "id": "my-ollama",
      "label": "My Ollama · Qwen3 Coder 30B",
      "provider": "ollama",
      "base_url": "http://127.0.0.1:11434",
      "model": "qwen3-coder:30b",
      "timeout_seconds": 60
    }
  ]
}
```

Replace the address with your Ollama computer's private LAN or Tailscale IP when
it runs on another computer. This explicit server configuration allows private
HTTP addresses; public endpoints require HTTPS. No cloud API key is forwarded to
Ollama. Keep the host running and the private network connected. No model download
or change to another app's configuration is performed.

Restart ProSe after changing the file. For example:

```powershell
python -m prose.cli serve --host 127.0.0.1 --port 8004 --ai-provider chatjimmy
```

The file's `default` controls the initial choice in debate practice and the live
HUD. A saved browser choice takes precedence in practice. The microphone CLI also
uses this registry; set `model_id` in its context JSON to override the default.
Ollama requests use its documented
[`/v1/chat/completions` interface](https://docs.ollama.com/api/openai-compatibility),
JSON mode, and `max_tokens`. Each request supplies the conversation independently.
The opponent has one spoken-response field, so ProSe also accepts a complete,
bounded plain-text opponent reply from compatible endpoints. Coach suggestions,
HUD cues and legal reviews still require valid JSON; truncated replies, malformed
JSON objects, tool calls and refusals are rejected.
The 60-second Ollama timeout allows for model loading; two model calls are required
for a full opponent-and-coach round. It is not a realtime latency guarantee.

### MLX main model and Saul 7B legal consultation

Profiles also accept `"provider": "mlx"` with an OpenAI-compatible `/v1` base URL.
For the Mac Studio Qwen3.6 installation use the proxy at port **8083**, with the
exact model ID `/Users/jasonbohan/mlx-env/models/Qwen3.6-35B-A3B-RAM-19GB-MLX`.
The profile label is just display text; the model ID must match the server's path.

Add a Saul profile and set the top-level `"legal_specialist": "saul-7b"`:

```json
{
  "id": "saul-7b",
  "label": "Saul 7B · Legal specialist",
  "provider": "ollama",
  "base_url": "http://100.90.227.86:11435/v1",
  "model": "prose-saul-7b:q4",
  "timeout_seconds": 60
}
```

The current Mac installation uses the community
[Saul 7B Q4_K_M GGUF](https://huggingface.co/MaziyarPanahi/Saul-Instruct-v1-GGUF)
(about 4.4 GB) through a dedicated Ollama process on Tailscale port 11435.
`prose-saul-7b:q4` is an alias with an 8192-token context, temperature 0.1 and
`num_gpu: 0`. It shares the downloaded weights rather than duplicating them.
Its process ID and log are in `~/mlx-env/prose-saul/ollama.pid` and `ollama.log`.
This process is not installed as a login service. To restart it on the Mac:

```sh
OLLAMA_HOST=100.90.227.86:11435 OLLAMA_NUM_PARALLEL=1 \
  OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_CONTEXT_LENGTH=4096 \
  /opt/homebrew/bin/ollama serve
```

The alias overrides the default context size. The two large Qwen models should
not be loaded together on this 32 GB Mac. Even Qwen3.6 plus GPU-resident Saul
exceeded the Metal memory limit in a live check, so Saul uses CPU inference.
CPU reviews can be slow; an elapsed budget or unavailable specialist is reported
in the review panel. Selecting a profile does not manage remote server lifecycles.

Enable **Consult legal specialist (Saul)** before starting practice or a live
session. The main coach drafts a response and decides whether to ask a focused
legal question. Saul receives bounded excerpts of the recent conversation,
jurisdiction and selected sources. The main coach then considers the review and
revises its suggestion. Ordinary debate can skip the specialist. The opponent
never receives the private coach's review. No recursive delegation or model tools
are enabled.

Practice allows a 90-second consultation budget; the live HUD allows 13 seconds
within its existing 15-second stale-cue cutoff. If review or synthesis fails,
ProSe preserves a usable draft and labels the incomplete review. If the primary
draft itself is invalid, the normal retry behavior applies. Reviews appear on
the companion; compact glasses frames retain only the final cue.

`legal_review: true` also enables consultation in CLI context JSON. Choose a main
model different from the specialist. Source IDs are checked against the supplied
excerpts; this checks provenance, not legal correctness. Neither model agreement
nor the name “legal specialist” establishes that a claim is correct or current.
The current setup is inference with existing weights, not a newly trained adapter.

For a repeatable comparison of already-running models, use
`scripts/compare_models.py --base-url URL/v1 --model MODEL --output REPORT.json`
with the repository on `PYTHONPATH`. Its nine original smoke cases include legal
reasoning, source handling, speaker tracking, JSON formatting and consultation
routing. Inspect the saved raw replies; a formatting pass is not a legal-accuracy
score or evidence of passing the bar exam.

### Experimental ChatJimmy practice

The ChatJimmy demo currently exposes `llama3.1-8B`. Start a local practice room:

```powershell
python -m prose.cli serve --port 8003 --ai-provider chatjimmy
```

This uses the public demo's native `/api/chat` interface without an API key.
The adapter sends system and user messages, checks the completion footer, and
accepts only valid JSON for app responses. It keeps recent context within a
bounded request size; older turns remain in your downloadable transcript.
It accepts one complete JSON object surrounded by harmless prose or code fences.
A completed but malformed reply receives one format retry within the original
timeout. Failed or unfinished replies are rejected without committing the turn;
there are no retries for HTTP errors, quota limits, or unfinished generations.
Your draft remains available so you can switch models and resend it.

This is an experimental demo integration. The supported
[Taalas API](https://api.taalas.com/) requires a key; its
[access request page](https://taalas.com/api-request-form/) was closed on 2026-10-01.
Review Taalas' [integration terms](https://taalas.com/terms-conditions/) before
distributing an integration. Demo availability and response format can change.
Llama 3.1 8B has not been shown here to meet the app's legal reasoning goals.

### Free AI option: Groq

For debate practice, Groq offers `openai/gpt-oss-120b` on its Free plan.
Create a key in the [Groq console](https://console.groq.com/keys), then launch
the app from a terminal. This prompt hides the key and holds it only in the
server process; it does not write it to source files or browser storage:

```powershell
python -m prose.cli serve --port 8004 --ai-provider groq --ask-ai-key
```

Open `http://127.0.0.1:8004/practice`. The launch flag selects Groq even when
`GEMINI_API_KEY` is already configured. It clears old custom endpoint/model
overrides for this process; `--ai-model` can set an explicit model instead.
For an existing server environment, use `PROSE_AI_PROVIDER=groq` and
`GROQ_API_KEY`; clear any old `PROSE_AI_BASE_URL` / `PROSE_AI_MODEL` overrides.

On 2026-10-01, Groq's published free limits for this model were 30 requests/minute,
1,000 requests/day, 8,000 tokens/minute and 200,000 tokens/day. Any limit can be
reached first, especially as conversations grow. Account limits are authoritative.
See [Groq limits](https://console.groq.com/docs/rate-limits) and the
[model page](https://console.groq.com/docs/model/openai/gpt-oss-120b).
This is a candidate to evaluate for debate and reasoning; switching models does
not establish legal accuracy or a bar-exam score.

For future source-backed research, [Tavily Search](https://docs.tavily.com/documentation/api-credits)
offers 1,000 free credits/month, with basic search costing one credit.
That is a separate source-retrieval service, not the debate model. Tavily is not
connected in this implementation. The current practice page correctly labels its
factual claims as not live-verified.

### Vocabulary data and offline dictionary

The word notebook at `/vocabulary` works without an AI key. It saves to
`.prose/vocabulary.sqlite3` by default; set `PROSE_DATA_DIR` before starting the
server to choose another location. Notes, recall schedules and usage history
survive restarts. JSON backup/import and Anki text export are available on the page.

Run `python -m prose.lexicon` once while online to install Open English WordNet
2025 (about 10 MB compressed). The online dictionary is optional and falls back
to the installed lexicon, cached results or saved words. Switch off **Use online
dictionary** for local-only lookup. The local ProSe server still needs to run.
See [VOCABULARY.md](VOCABULARY.md) for attribution, backup behavior and limits.

The live coach uses the Python standard library and an OpenAI-compatible
`/chat/completions` endpoint with JSON output. It adds no required packages.
Configure environment variables **before** starting `prose serve` or `prose listen`.
Keys stay on the server and are never included in HUD frames or page content.

PowerShell examples (use the model identifier available to your account/server):

```powershell
# Gemini: a GEMINI_API_KEY already in the environment is detected automatically.
$env:GEMINI_API_KEY = 'YOUR_KEY'
$env:PROSE_AI_MODEL = 'gemini-2.5-flash'
prose serve

# OpenAI: choose an available text model with Chat Completions JSON support.
$env:PROSE_AI_BASE_URL = 'https://api.openai.com/v1'
$env:OPENAI_API_KEY = 'YOUR_KEY'
$env:PROSE_AI_MODEL = 'YOUR_MODEL_ID'
prose serve

# Local model, for example a model already served through Ollama's compatible API.
$env:PROSE_AI_BASE_URL = 'http://127.0.0.1:11434/v1'
$env:PROSE_AI_MODEL = 'YOUR_INSTALLED_MODEL'
prose serve
```

For other HTTPS providers, set `PROSE_AI_BASE_URL`, `PROSE_AI_MODEL`, and
`PROSE_AI_API_KEY`. Provider-specific keys are used only with their matching
hosts. HTTP is allowed only for loopback endpoints. The live HUD request timeout
defaults to 12 seconds; `PROSE_AI_TIMEOUT` accepts 1–60 seconds, although live cues older
than 15 seconds are discarded. Each completed turn can produce one model call;
pending turns are coalesced during slow inference. There are no automatic retries.

For a simulated AI opponent, open `http://127.0.0.1:8000/practice`. Pick a topic,
your position, outlook and temperament. Start practice, use or edit the opening
suggestion, and send your reply. The opponent and private coach use separate
model calls; allow up to twice the configured provider timeout per round.
Practice defaults to 30 seconds per call and a 4,096-token completion budget
for its longer learning feedback; the live HUD retains its 2,048-token budget.
`PROSE_AI_TIMEOUT`, when set, overrides the timeout for both modes.
Browser dictation and speech playback are optional. Text chat works without
glasses. The API uses JSON POST requests to `/api/practice/sessions`, `/turn`,
`/state`, and `/stop`. A turn requires `session_id`, `text`, and `expected_turn`
(the zero-based completed round count); stale or concurrent requests return 409.
State can be fetched after a lost response to avoid sending a duplicate reply.

If Gemini returns HTTP 429, check the project's
[usage and rate limits](https://aistudio.google.com/usage?tab=rate-limit).
The app distinguishes an exhausted daily request quota from a generic rate limit.
Daily quotas reset at midnight Pacific time; limits apply to the project, not
individual API keys. A new key in the same project does not add quota. To keep
using a hosted model beyond its free allowance, manage billing or quota in your
provider account. No automatic paid upgrade or model substitution is performed.
See Google's [rate-limit guide](https://ai.google.dev/gemini-api/docs/rate-limits).

Open `http://127.0.0.1:8000/copilot`. Choose a mode and enter your position or
case brief. Litigation settings include direct/cross examination, argument,
deposition, governing jurisdiction, and an optional supplied local rule. Federal
evidence summaries are included only when you select **US federal**. Select up
to six Discovery documents (first 3,000 characters each) if useful. The recent
16 transcript turns, session brief, and selected excerpts go to the configured
model; older turns are not automatically summarized. Put lasting facts in notes.
Stop and start a session to change its brief or sources.

Browser speech recognition requires browser support and microphone permission;
the browser may use a remote speech service. Speaker identity is set manually,
not inferred. Use the existing Vosk microphone CLI for local audio transcription.
Model reasoning remains remote when a hosted endpoint is configured.

Example `case.json` for CLI coaching:

```json
{
  "role": "Plaintiff, self-represented",
  "goal": "Establish which charges the witness personally reviewed",
  "jurisdiction": "US federal",
  "stage": "cross",
  "notes": "The billing statement was authenticated and admitted. Liability is disputed."
}
```

```sh
prose listen --mic --model PATH_TO_VOSK_MODEL --assist litigation --context case.json --speaker Witness --transport jsonl=live_hud.jsonl
prose glasses --jsonl live_hud.jsonl
```

The glasses/phone bridge receives the existing `seq`, `speaker`, `transcript`,
`prompt`, and `objections` fields, plus `status`, `turn_id`, `latency_ms`,
`expires_at` (Unix seconds), `error`, `momentum_pct` (0-100, 50 = even), and a
structured `cue` (now also carrying `mood_label`, `mood_intensity` 1-5, and
`momentum_signal`). Render `prompt` as the short cue; retain `cue.rationale`,
`cue.next_question`, `cue.caveat`, and `cue.sources` for the companion. Only a
`status: "ready"` frame should replace what's displayed -- including a null
prompt, which means "explicitly nothing to add" and clears the display. Every
other status (`thinking`, `unavailable`, `expired`, `listening`) is a no-op for
display purposes; a receiver should keep showing its last `ready` frame rather
than clearing on a timer. Suggestions are advisory; source IDs are checked
against supplied material, but interpretations are not independently verified.
Model-reported confidence is not treated as a probability. The mood and
momentum fields are playful, subjective engagement signals derived from the
model's read of the transcript -- not a prediction of legal merit or debate
outcome, and should not be treated as case-strength guidance.

For a phone-to-glasses link, use `--compact-hud` on `prose listen` or request
`/api/copilot/events?session_id=…&view=glasses`. The compact version-2 frame has
`seq`, `turn_id`, `status`, `speaker` (at most 40 characters), `prompt` (at most
140 characters), `mood_label`, `mood_intensity`, `momentum_pct`, and
`expires_at`. It omits transcripts, documents, and the longer explanation. The
phone retains the full companion frame and forwards the compact cue through
the glasses vendor's display SDK. A `ready` frame with a null prompt clears the
display; any other status leaves the current display untouched.

A session's coaching tone (directness, formality, encouragement, humor, each
0-4) can be adjusted live via `POST /api/copilot/tone` (also exposed as sliders
on the `/copilot` page) without restarting the session. A change takes effect
starting with the next transcript turn; it only affects delivery style, never
the underlying factual, citation, or evidentiary rules.

MemoMind One has a concrete [PhoneSDK display relay](integrations/memomind/README.md)
in this repository. The `/copilot` page exposes its private stream link after
starting a session. The relay uses the supplied GM Web Bridge and requests only
display/network permissions. Native MemoMind microphone integration remains a
separate Opus-to-transcript task; see the device README for the current SDK
contract, build instructions, and hardware validation requirements.

Local companion/bridge API:

- `GET /api/copilot/status` — model configuration summary (no credentials).
- `POST /api/copilot/sessions` — JSON session brief, optional `document_ids` and
  `governing_rule`; returns a random `session_id`.
- `POST /api/copilot/turn` — JSON `{ "session_id": "…", "speaker": "Witness",
  "text": "…" }`; immediately returns a transcript frame while inference runs.
- `GET /api/copilot/events?session_id=…` — live SSE `frame` events; supports
  `Last-Event-ID`, heartbeats, and a `stopped` event. Reconnect shows the latest state.
- `POST /api/copilot/stop` — JSON `{ "session_id": "…" }`; discards pending cues.

Sessions are kept in memory, isolated from each other, limited to eight active
sessions, and expire after 30 minutes without transcript input. Keep this
development server on loopback; it has no user authentication. Hardware-specific
BLE display rendering and microphone diarization remain integration work.

References: [OpenAI structured output documentation](https://developers.openai.com/api/docs/guides/structured-outputs),
[Gemini compatible API](https://ai.google.dev/gemini-api/docs/openai), and
[Federal Rules of Evidence, December 1, 2025](https://www.uscourts.gov/sites/default/files/document/federal-rules-of-evidence.pdf).
The bundled federal summaries were checked against that edition on 2026-10-01.

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
