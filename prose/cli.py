from __future__ import annotations

import argparse
import getpass
import json
import os
import warnings
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .briefing import brief_for_stage
from .crawler import (
    Violation,
    build_live_sources,
    collect,
)
from .device import open_transport
from .pipeline import run
from .tagger import SAMPLE_RAW_COMPLAINT, tag_text


def describe_violation(violation: Violation) -> str:
    rules = ",".join(rule["type"] for rule in violation.rules)
    return (
        f"[{violation.source}] {violation.id} {violation.program} "
        f"({violation.status}) rules: {rules or 'none'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="prose",
        description="Project JusticeStack / LexGlasses - pro se litigation assistant",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    sim = subparsers.add_parser("simulate", help="run the end-to-end demo pipeline")
    sim.add_argument(
        "--transport",
        default="console",
        help="HUD transport: console | jsonl[=file] | ws=url (streams frames in real time)",
    )

    tag_cmd = subparsers.add_parser(
        "tag", help="tag raw text (or the built-in sample) with basic entities"
    )
    tag_cmd.add_argument("path", nargs="?", help="path to a raw document to tag")

    brief_cmd = subparsers.add_parser(
        "briefing", help="show the pre-prepared checklist for a case stage"
    )
    brief_cmd.add_argument("stage", help="case stage, e.g. DISCOVERY")

    ingest_cmd = subparsers.add_parser(
        "ingest", help="fetch live violations from public sources (CFPB, RECAP, FTC press releases)"
    )
    ingest_cmd.add_argument("--source", choices=("cfpb", "recap", "ftc", "all"), default="all")
    ingest_cmd.add_argument("--query", default=None, help="search term for cfpb/recap")
    ingest_cmd.add_argument("--limit", type=int, default=10, help="max items per source")
    ingest_cmd.add_argument("--out", default=None, help="write violations as JSON to this path")

    serve_cmd = subparsers.add_parser(
        "serve", help="run the web dashboard + JSON API + SSE HUD stream"
    )
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8000)
    serve_cmd.add_argument("--ai-provider", choices=("chatjimmy", "groq", "gemini", "openai"),
                           help="select a hosted AI provider for this server run")
    serve_cmd.add_argument("--ai-model", help="override this provider's model")
    serve_cmd.add_argument("--ask-ai-key", action="store_true",
                           help="prompt privately for an API key; keep it only for this run")

    listen_cmd = subparsers.add_parser(
        "listen",
        help="stream a WAV file or live microphone through ASR into the HUD pipeline "
        "(requires vosk + a model)",
    )
    listen_cmd.add_argument(
        "wav_path", nargs="?", help="path to a 16-bit mono PCM WAV file (omit with --mic)"
    )
    listen_cmd.add_argument(
        "--mic",
        action="store_true",
        help="capture from the default microphone instead of a WAV file (Ctrl+C to stop)",
    )
    listen_cmd.add_argument(
        "--duration",
        type=float,
        default=None,
        help="stop --mic capture after N seconds (unbounded by default)",
    )
    listen_cmd.add_argument("--model", required=True, help="path to a downloaded Vosk model dir")
    listen_cmd.add_argument(
        "--assist", choices=("litigation", "debate"),
        help="enable context-aware AI cues in the background (configured via PROSE_AI_*)",
    )
    listen_cmd.add_argument(
        "--context", help="JSON session brief: role, goal, jurisdiction, stage, notes"
    )
    listen_cmd.add_argument("--speaker", default="Speaker", help="speaker label (no diarization)")
    listen_cmd.add_argument(
        "--compact-hud", action="store_true",
        help="emit only the short cue and expiry for a phone-to-glasses bridge",
    )
    listen_cmd.add_argument(
        "--transport",
        default="console",
        help="HUD transport: console | jsonl[=file] | ws=url",
    )

    glasses_cmd = subparsers.add_parser(
        "glasses",
        help="terminal HUD emulator: render a jsonl or ws= frame stream like a glasses display",
    )
    glasses_source = glasses_cmd.add_mutually_exclusive_group(required=True)
    glasses_source.add_argument("--jsonl", default=None, help="path to a jsonl transport's output")
    glasses_source.add_argument("--ws", default=None, help="ws:// url of a running ws= transport")
    glasses_cmd.add_argument(
        "--from-start",
        action="store_true",
        help="with --jsonl, replay the whole file instead of tailing new lines only",
    )
    glasses_cmd.add_argument("--history", type=int, default=8, help="frames kept on screen")

    args = parser.parse_args(argv)
    if args.command == "simulate":
        print(run(transport=open_transport(args.transport)).to_text())
    elif args.command == "tag":
        text = Path(args.path).read_text(encoding="utf-8") if args.path else SAMPLE_RAW_COMPLAINT
        print(tag_text(text).summary())
    elif args.command == "briefing":
        print(brief_for_stage(args.stage.upper()).to_text())
    elif args.command == "ingest":
        live_sources = build_live_sources(args.source, args.query, args.limit)
        violations = collect(live_sources, rate_limit_seconds=1.0)
        for violation in violations:
            print(describe_violation(violation))
        print(f"fetched {len(violations)} violation(s) from "
              f"{', '.join(s.name for s in live_sources)}")
        if args.out:
            payload = []
            for v in violations:
                item = asdict(v)
                item["window_start"] = v.window_start.isoformat()
                item["window_end"] = v.window_end.isoformat()
                payload.append(item)
            Path(args.out).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    elif args.command == "serve":
        from .web import serve

        if args.ask_ai_key and not args.ai_provider:
            parser.error("--ask-ai-key requires --ai-provider")
        if args.ask_ai_key and args.ai_provider == "chatjimmy":
            parser.error("ChatJimmy's public demo does not accept a user API key")
        if args.ai_provider:
            os.environ["PROSE_AI_PROVIDER"] = args.ai_provider
            os.environ.pop("PROSE_AI_BASE_URL", None)
            os.environ.pop("PROSE_AI_API_KEY", None)
            os.environ.pop("PROSE_AI_MODEL", None)
            if args.ai_provider == "openai" and not args.ai_model:
                parser.error("--ai-provider openai requires --ai-model")
        if args.ai_model:
            os.environ["PROSE_AI_MODEL"] = args.ai_model
        if args.ask_ai_key:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    prompt = f"{args.ai_provider.title()} API key (hidden): "
                    secret = getpass.getpass(prompt).strip()
            except (getpass.GetPassWarning, EOFError):
                parser.error("Use an interactive terminal for hidden key entry, "
                             "or configure the provider's API-key environment variable.")
            if not secret:
                parser.error("An API key is required")
            key_name = {"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY",
                        "openai": "OPENAI_API_KEY"}[args.ai_provider]
            os.environ[key_name] = secret
            del secret
        serve(args.host, args.port)
    elif args.command == "listen":
        import sys
        import time

        from .asr import StreamingHudSession, VoskTranscriber
        from .audio import MicrophoneSource, WavFileSource

        copilot = None
        if args.assist:
            from .copilot import CopilotSession, ModelCoach, SessionConfig, selected_sources
            from .legal_specialist import ConsultingCoach
            from .model_choices import ModelChoices

            brief = (
                json.loads(Path(args.context).read_text(encoding="utf-8")) if args.context else {}
            )
            if not isinstance(brief, dict):
                raise SystemExit("--context must contain a JSON object")
            brief["mode"] = args.assist
            config = SessionConfig.from_dict(brief)
            choices = ModelChoices()
            _, settings = choices.resolve(brief.get("model_id"))
            coach = ModelCoach(settings)
            if config.legal_review:
                coach = ConsultingCoach(coach, ModelCoach(choices.specialist(),
                                                         max_completion_tokens=900))
            print(f"[prose.cli] {args.assist} coach: {settings.model}; "
                  "transcripts and context are sent to the configured model", file=sys.stderr)
            copilot = CopilotSession(config, coach, selected_sources(
                brief, [], litigation=config.mode == "litigation"))
        elif args.context:
            raise SystemExit("--context requires --assist litigation or --assist debate")

        if args.mic:
            print("[prose.cli] opening microphone...", file=sys.stderr)
            source = MicrophoneSource()
        elif args.wav_path:
            source = WavFileSource(args.wav_path)
        else:
            raise SystemExit("listen requires either a wav_path or --mic")

        print(f"[prose.cli] loading Vosk model from {args.model} ...", file=sys.stderr)
        session = StreamingHudSession(
            VoskTranscriber(args.model, sample_rate=source.sample_rate),
            simulator=copilot, speaker=args.speaker,
        )
        transport = open_transport(args.transport, compact=args.compact_hud)
        if args.mic:
            stop_hint = f"stopping after {args.duration}s" if args.duration else "Ctrl+C to stop"
            print(f"[prose.cli] listening ({stop_hint}); speak now...", file=sys.stderr)
        started = time.monotonic()
        frame_count = 0
        sent_seq = 0
        try:
            for chunk in source.chunks():
                frame = session.accept_audio(chunk)
                if frame is not None:
                    frame_count += 1
                    print(
                        f"[prose.cli] frame #{frame_count}: {frame.transcript.text!r}"
                        f"{' -- OBJECTION' if frame.objections else ''}",
                        file=sys.stderr,
                    )
                    if copilot is None:
                        transport.send(frame)
                if copilot is not None:
                    for update in copilot.frames_after(sent_seq)[-1:]:
                        transport.send(update)
                        sent_seq = update.seq
                if args.duration is not None and time.monotonic() - started >= args.duration:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            source.close()
            final_frame = session.close()
            if copilot is not None:
                # Drain on the thread that owns the transport's event loop.
                if not args.mic:
                    copilot.wait_idle(timeout=15)
                for update in copilot.frames_after(sent_seq)[-1:]:
                    transport.send(update)
                    sent_seq = update.seq
                copilot.close()
            elif final_frame is not None:
                transport.send(final_frame)
            transport.close()
            print(f"[prose.cli] stopped; {frame_count} frame(s) sent.", file=sys.stderr)
    elif args.command == "glasses":
        import sys

        from .glasses_emulator import TerminalGlassesEmulator, consume_jsonl, consume_ws

        emulator = TerminalGlassesEmulator(history=args.history)
        if args.jsonl:
            print(f"[prose.cli] waiting for frames in {args.jsonl} ...", file=sys.stderr)
            source = consume_jsonl(args.jsonl, from_start=args.from_start)
        else:
            print(f"[prose.cli] connecting to {args.ws} ...", file=sys.stderr)
            source = consume_ws(args.ws)
        try:
            for frame in source:
                emulator.feed(frame)
        except KeyboardInterrupt:
            pass
    else:
        print(run().to_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
