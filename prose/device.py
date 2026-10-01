from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from .hud import HudFrame


class HudTransport:
    def send(self, frame: HudFrame) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


def frame_to_payload(frame: HudFrame) -> dict:
    return {
        "seq": frame.seq,
        "speaker": frame.transcript.speaker,
        "transcript": frame.transcript.text,
        "prompt": frame.prompt,
        "objections": [
            {
                "rule": o.rule_id,
                "label": o.label,
                "citation": o.citation,
                "prompt": o.prompt,
                "hits": list(o.hits),
                "confidence": o.confidence,
            }
            for o in frame.objections
        ],
    }


def format_frame(frame: HudFrame) -> str:
    lines = [f"#{frame.seq} {frame.transcript.speaker}: {frame.transcript.text}"]
    for objection in frame.objections:
        lines.append(
            f"   OBJECTION  {objection.label} ({objection.citation}) "
            f"conf={objection.confidence:.2f}"
        )
    if frame.prompt is not None:
        lines.append(f"   HUD PROMPT> {frame.prompt}")
    else:
        lines.append("   HUD: -- no prompt --")
    return "\n".join(lines)


class ConsoleTransport(HudTransport):
    def __init__(self, out: object | None = None) -> None:
        self._out = out if out is not None else sys.stdout

    def send(self, frame: HudFrame) -> None:
        print(format_frame(frame), file=self._out)

    def close(self) -> None:
        return None


class JsonLinesTransport(HudTransport):
    def __init__(self, stream: object, owns_stream: bool = False) -> None:
        self._stream = stream
        self._owns_stream = owns_stream

    def send(self, frame: HudFrame) -> None:
        self._stream.write(json.dumps(frame_to_payload(frame)) + "\n")

    def close(self) -> None:
        if self._owns_stream:
            self._stream.close()


class WebSocketTransport(HudTransport):
    def __init__(self, url: str) -> None:
        self._url = url
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        # A websocket connection's internal futures/locks are bound to the loop
        # that created it, so the connection must be driven by that same loop
        # for its whole lifetime -- not a fresh one per send/close call.
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop

    def _connect(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError(
                "ws transport requires the 'websockets' package (pip install websockets)"
            ) from exc
        loop = self._ensure_loop()
        self._ws = loop.run_until_complete(websockets.connect(self._url))

    def send(self, frame: HudFrame) -> None:
        if self._ws is None:
            self._connect()
        loop = self._ensure_loop()
        loop.run_until_complete(self._ws.send(json.dumps(frame_to_payload(frame))))

    def close(self) -> None:
        if self._ws is not None:
            loop = self._ensure_loop()
            loop.run_until_complete(self._ws.close())
            self._ws = None
        if self._loop is not None:
            self._loop.close()
            self._loop = None


def open_transport(spec: str) -> HudTransport:
    if spec == "console":
        return ConsoleTransport()
    if spec == "jsonl":
        return JsonLinesTransport(
            Path("prose-hud.jsonl").open("a", encoding="utf-8"), owns_stream=True
        )
    if spec.startswith("jsonl="):
        return JsonLinesTransport(
            Path(spec.partition("=")[2]).open("a", encoding="utf-8"), owns_stream=True
        )
    if spec.startswith("ws="):
        return WebSocketTransport(spec.partition("=")[2])
    if spec.startswith("ws://"):
        return WebSocketTransport(spec)
    raise ValueError(f"unknown transport spec: {spec}")