# ProSe — Project JusticeStack / LexGlasses

End-to-end pro se litigation assistant: court/regulatory ingestion → consumer-violation & class-action matcher → jurisdictional document generation → lawsuit state machine → smart-glasses objection/teleprompter HUD.

> **Not legal advice.** All generated documents are drafts that assist self-representation. Verify every citation, local rule, and deadline with a qualified attorney in your jurisdiction before filing.

## Quickstart

Scouting guideline debates now have a searchable local research library at `/research`.
See [RESEARCH.md](RESEARCH.md) for national-source coverage, offline storage and
importing a situation folder downloaded from Google Drive.

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

## Vocabulary builder with offline practice

Open `/vocabulary` for a saved word notebook, root/family notes, your own
explanations and sentences, and spaced recall. The 24 original starter cards
cover evidence, reasoning, precision, listening and policy. Select focus words
before opening a debate: the private coach receives up to three, explains their
nuance, and gives feedback on your actual usage. Debate use does not automatically
advance recall progress.

Dictionary lookups try [FreeDictionaryAPI.com](https://freedictionaryapi.com/)
and retain licensed results locally. If unavailable, they fall back to cached
results, an installed Open English WordNet dictionary, or saved notebook entries.
Turn off online lookup to keep requests local. Install the full offline dictionary:

```sh
python -m prose.lexicon
```

Personal notes and progress use SQLite transactions in `.prose/vocabulary.sqlite3`.
Download/import a versioned JSON backup from the page, or export tab-separated
cards for Anki. Reviews use a transparent Leitner schedule; Anki's scheduler is
not embedded. The local app must be running for offline study. Hosted AI debate
still requires connectivity unless you configure a local model.

See [the learning and data guide](VOCABULARY.md) for sources, backup behavior,
offline scope, and the Bo Seo-inspired listening exercises.

## Debate practice without glasses

Start the experimental ChatJimmy demo connection without an API key:

```sh
python -m prose.cli serve --port 8003 --ai-provider chatjimmy
```

The provider is identified as Llama 3.1 8B; the public demo can change or become
unavailable. [SETUP.md](SETUP.md) also covers Groq's free API plan and private key entry.

Open `/practice` to debate a real AI opponent with a separate private coach.
Use the **AI model** menu to select ChatJimmy or a configured Ollama or MLX model. You can
switch between turns while keeping the conversation and your draft. See
[model selection setup](SETUP.md#choose-the-debate-model-including-your-own-ollama-host)
to add a Mac Studio or another model host. Enable **Consult legal specialist
(Saul)** for a separate legal review before your coach finalizes a suggestion.
Review status and source references appear beside the coach. See
[Saul setup and memory limits](SETUP.md#mlx-main-model-and-saul-7b-legal-consultation).
Choose your topic, your position, an opponent outlook (including MAGA supporter,
progressive, libertarian, skeptic, opposing counsel, or custom), and temperament
(curious, firm, stubborn, or combative). The coach suggests your opening; edit it
or write your own, send it, and the opponent responds in character. Each round
includes feedback and a suggested next reply. Optional browser dictation and
read-aloud let you practice speaking. No glasses are required.

Practice uses the same model configuration described below. Each reply makes
two separate model calls: opponent first, coach second. Personas are fictional;
claims are not automatically fact-checked. Sessions retain up to 20 rounds in
memory and expire after 30 idle minutes or a server restart. Download the
conversation before ending if you want to keep it.

## Phone controller and HUD launcher

Open `/controller` on your phone to drive the whole loop. The page opens a
gamepad menu that moves the **HUD launcher** running on the glasses (`/hud/stream`):
pick Debate practice or Litigation practice, configure the session — topic,
position, opponent, and up to six case files from your library — then fight it
round by round. The view shows an animated confidence meter (it flashes when a
rebuttal lands and the opponent's face reacts on the glasses), slide-in
transcript bubbles, and the coach's suggested reply you can send or edit.
Paste the glasses stream link shown on the page into the MemoMind relay once;
menu, confidence, mood, and cues then follow live. Same disclaimer: preparation
aid only, not legal advice.

## Live litigation and debate coach

Open `/copilot` after `prose serve` to start a **Debate coach** or **Litigation
coach** session. Supply your role, objective, case notes, and source documents;
then paste transcript turns or enable the browser microphone. The glasses
preview shows one short suggestion, while the companion shows its explanation,
follow-up question, uncertainty, and supplied sources.

For the microphone-to-glasses pipeline:

```sh
prose listen --mic --model PATH_TO_VOSK_MODEL --assist debate --transport jsonl=live_hud.jsonl
prose listen --mic --model PATH_TO_VOSK_MODEL --assist litigation --context case.json --transport ws=ws://127.0.0.1:9000
```

The optional model runs in a background worker, retains 16 recent turns, and
coalesces pending requests. New speech clears the previous cue; obsolete
responses and responses older than 15 seconds are discarded. Visible cues
expire after 15 seconds. Existing simulation and rule-based commands remain
available without a model.

Configure a local or hosted OpenAI-compatible endpoint as described in
[SETUP.md](SETUP.md#live-coach-model-configuration). A Gemini key already in the
environment enables the default `gemini-2.5-flash` configuration; model access
and response time still depend on the provider. Transcripts are sent only when
you explicitly start a coaching session or use `--assist`.

This adds context-aware model inference, not a measured bar exam qualification.
Legal accuracy and useful response time still need evaluation on realistic
transcripts and the target glasses. The included federal evidence summaries
are narrow reference aids; state rules require supplied jurisdictional context.

For **MemoMind One**, [the PhoneSDK display relay](integrations/memomind/README.md)
uses the vendor's `gm.display` interface and the session's compact stream link.
The relay source and device setup are included; installation, glasses audio
decoding, and physical phone/glasses validation are still required.

Environment setup, live data-source notes, and the "intentionally not used" list live
in [SETUP.md](SETUP.md).

## Layout

```
prose/crawler.py        ingestion (mock + live sources, pluggable Source protocol)
prose/matcher.py        consumer violation / class-action matcher (rule types)
prose/docs.py           jurisdictional template rendering (draft documents)
prose/state_machine.py  lawsuit stage tracking with validated transitions
prose/hud.py            ASR stub + FRE objection engine + teleprompter
prose/copilot.py        contextual model coaching + bounded asynchronous sessions
prose/copilot_web.py    live companion, debate/courtroom controls, glasses preview
prose/debate.py         AI practice opponent, private coach, bounded turn history
prose/debate_web.py     practice room, personalities, editable cues, browser voice
prose/device.py         HUD transport layer (console, JSONL stream, WebSocket)
prose/web.py            web dashboard (discovery review + wikilink graph,
                        recall search, class actions, collections, SSE HUD)
prose/tagger.py         batch entity tagging (dates, parties, amounts, keywords)
prose/briefing.py       pre-prepared stage briefings checklist lookup
prose/pipeline.py       end-to-end wiring (confidence threshold + human review queue)
prose/cli.py            command-line entry point
prose/data/             objection rules, sample violation feed, briefings, form templates
```

## Design for low-capability models

The original simulation pipeline assumes a low-capability model (or none at all)
in the hot path. The optional live coach adds a separate model worker:

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
