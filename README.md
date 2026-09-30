# ProSe — Project JusticeStack / LexGlasses

End-to-end pro se litigation assistant: court/regulatory ingestion → consumer-violation & class-action matcher → jurisdictional document generation → lawsuit state machine → smart-glasses objection/teleprompter HUD.

> **Not legal advice.** All generated documents are drafts that assist self-representation. Verify every citation, local rule, and deadline with a qualified attorney in your jurisdiction before filing.

## Quickstart

```
python -m prose.cli simulate                          # end-to-end demo pipeline
python -m prose.cli simulate --transport jsonl=hud.jsonl   # stream HUD frames as JSON lines
python -m prose.cli simulate --transport ws=ws://127.0.0.1:9000  # stream over WebSocket
python -m prose.cli tag [path-to-raw-doc]              # batch entity tagging (dates/parties/amounts/keywords)
python -m prose.cli briefing DISCOVERY                 # pre-prepared checklist for a case stage
python -m prose.cli ingest --source all --limit 5      # live fetch: CFPB, RECAP (CourtListener), FTC press releases
python -m prose.cli ingest --source cfpb --query "late fee" --out feed.json
python -m prose.cli listen recording.wav --model vosk-model-small-en-us-0.15  # live ASR -> HUD
python -m prose.cli serve                              # web dashboard + JSON API + SSE HUD stream (http://127.0.0.1:8000)
python -m pytest               # test suite
python -m pytest -k emulation  # network/device/ASR emulation tests only
python -m ruff check .         # lint
```

Environment setup, live data-source notes, and the "intentionally not used" list live
in [SETUP.md](SETUP.md).

## Layout

```
prose/crawler.py        ingestion (mock + live sources, pluggable Source protocol)
prose/matcher.py        consumer violation / class-action matcher (rule types)
prose/docs.py           jurisdictional template rendering (draft documents)
prose/state_machine.py  lawsuit stage tracking with validated transitions
prose/hud.py            ASR stub + FRE objection engine + teleprompter
prose/device.py         HUD transport layer (console, JSONL stream, WebSocket)
prose/web.py            web dashboard (ThreadingHTTPServer + SSE HUD stream)
prose/tagger.py         batch entity tagging (dates, parties, amounts, keywords)
prose/briefing.py       pre-prepared stage briefings checklist lookup
prose/pipeline.py       end-to-end wiring (confidence threshold + human review queue)
prose/cli.py            command-line entry point
prose/data/             objection rules, sample violation feed, briefings, form templates
```

## Design for low-capability models

The pipeline assumes a low-capability model (or none at all) in the hot path:

- **Batch processing**: ingestion, matching, tagging, and doc rendering are one-shot batch jobs, not real-time inference.
- **Keyword/rule matching**: the matcher, tagger, and HUD objection engine are regex/keyword lookups, not LLM calls.
- **Template filling**: drafts are `{{TOKEN}}` substitutions over vetted templates; no free-form generation.
- **Confidence threshold + human fallback**: matches with confidence below `MIN_AUTO_CONFIDENCE` (0.75) go to a review queue; nothing auto-generates for them.
- **Human-in-the-loop**: reviews are flagged as "verify manually before acting"; drafts carry the not-legal-advice disclaimer and pass `validate_draft` (no unresolved tokens, disclaimer present).
- **Pre-prepared stage briefings**: `prose/data/briefings.json` supplies per-stage checklists that can be pushed to a phone prompt instead of generated in real time.

## Extending

- **Real ingestion** (implemented, stdlib-only): `CfpbSource` (Consumer Complaint Database v1 search API), `RecapSource` (CourtListener RECAP docket search, no key required), `FtcSource` (FTC consumer-protection press-release RSS). All implement `Source.fetch()`; `collect()` degrades per-source on failure. Matcher rules are keyword-derived (`derive_rules`: fee terms → `overcharge`, "auto-renew" → `auto_enroll`, SKU-like tokens → `recall`), nothing smarter is assumed. `simulate` stays offline (mocks by default); pass `sources=[...]` to `prose.pipeline.run()` or use `prose.cli ingest` for live data. Rate-limit, CAPTCHA, and schema-drift handling belongs in these adapters.
- **New matcher rules**: add a branch in `prose/matcher.py::_run_rule`.
- **New form types**: drop a template in `prose/data/templates/` and map it in `prose/docs.py::DOC_TYPES_BY_CLAIM`.
- **Real glasses link**: `prose/asr.py` implements the live-audio side — `VoskTranscriber` (offline streaming ASR via `pip install vosk` + a downloaded model, see `pip install ".[glasses]"`) and `StreamingHudSession`, which turns finalized utterances into the same `HudFrame` objects `MockASR`/`HudSimulator.feed()` produce. Try it with `prose.cli listen <file.wav> --model <vosk-model-dir>` (16-bit mono PCM WAV in, HUD frames out). The HUD engine emits those `HudFrame` objects regardless of source; route them to hardware through `prose/device.py`:
  - `jsonl=` — append a compact JSON-line per frame; consume with any companion app (Brilliant Labs Frame, OpenGlass, ESP32 DIY build) bridged over BLE/USB.
  - `ws=` — stream directly to a WebSocket bridge with the `websockets` package.
  - a `FrameTransport(HudTransport)` subclass wrapping the Brilliant Labs Python/BLE utilities (or OpenGlass's BLE service) is the remaining piece once the target glasses are chosen.
  - still unbuilt: live mic capture (today's input is a WAV file or pre-scripted text) and the on-glasses *renderer* that turns received frames into pixels — `prose/device.py` only gets JSON to the device, it doesn't draw anything.