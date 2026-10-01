from __future__ import annotations

import argparse
import json
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
        serve(args.host, args.port)
    elif args.command == "listen":
        import sys
        import time

        from .asr import StreamingHudSession, VoskTranscriber
        from .audio import MicrophoneSource, WavFileSource

        if args.mic:
            print("[prose.cli] opening microphone...", file=sys.stderr)
            source = MicrophoneSource()
        elif args.wav_path:
            source = WavFileSource(args.wav_path)
        else:
            raise SystemExit("listen requires either a wav_path or --mic")

        print(f"[prose.cli] loading Vosk model from {args.model} ...", file=sys.stderr)
        session = StreamingHudSession(VoskTranscriber(args.model, sample_rate=source.sample_rate))
        transport = open_transport(args.transport)
        if args.mic:
            stop_hint = f"stopping after {args.duration}s" if args.duration else "Ctrl+C to stop"
            print(f"[prose.cli] listening ({stop_hint}); speak now...", file=sys.stderr)
        started = time.monotonic()
        frame_count = 0
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
                    transport.send(frame)
                if args.duration is not None and time.monotonic() - started >= args.duration:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            source.close()
            final_frame = session.close()
            if final_frame is not None:
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