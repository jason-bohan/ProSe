from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .hud import HudFrame


class HudTransport:
    def send(self, frame: HudFrame) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


def frame_to_payload(frame: HudFrame) -> dict:
    payload = {
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
    if frame.status is not None:
        payload.update(status=frame.status, turn_id=frame.turn_id,
                       latency_ms=frame.latency_ms, error=frame.error,
                       expires_at=frame.expires_at,
                       cue=asdict(frame.cue) if frame.cue else None)
        if frame.legal_review is not None:
            payload["legal_review"] = frame.legal_review
    return payload


def frame_to_glasses_payload(frame: HudFrame) -> dict:
    """Small display update for a phone-to-glasses bridge; no case documents.

    A null prompt means clear the display. The receiver must also clear at the
    Unix timestamp expires_at, even when its connection stops receiving data.
    """
    return {
        "version": 1, "seq": frame.seq, "turn_id": frame.turn_id,
        "status": frame.status or "ready", "prompt": (frame.prompt or "")[:140] or None,
        "expires_at": frame.expires_at,
    }


def format_frame(frame: HudFrame) -> str:
    lines = [f"#{frame.seq} {frame.transcript.speaker}: {frame.transcript.text}"]
    if frame.status:
        lines.append(f"   ASSIST: {frame.status}" + (f" ({frame.error})" if frame.error else ""))
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
    def __init__(self, stream: object, owns_stream: bool = False, *, compact: bool = False) -> None:
        self._stream = stream
        self._owns_stream = owns_stream
        self._serialize = frame_to_glasses_payload if compact else frame_to_payload

    def send(self, frame: HudFrame) -> None:
        self._stream.write(json.dumps(self._serialize(frame)) + "\n")
        self._stream.flush()

    def close(self) -> None:
        if self._owns_stream:
            self._stream.close()


class WebSocketTransport(HudTransport):
    def __init__(self, url: str, *, compact: bool = False) -> None:
        self._url = url
        self._ws = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._serialize = frame_to_glasses_payload if compact else frame_to_payload

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
        loop.run_until_complete(self._ws.send(json.dumps(self._serialize(frame))))

    def close(self) -> None:
        if self._ws is not None:
            loop = self._ensure_loop()
            loop.run_until_complete(self._ws.close())
            self._ws = None
        if self._loop is not None:
            self._loop.close()
            self._loop = None


def open_transport(spec: str, *, compact: bool = False) -> HudTransport:
    if spec == "console":
        return ConsoleTransport()
    if spec == "jsonl":
        return JsonLinesTransport(
            Path("prose-hud.jsonl").open("a", encoding="utf-8"), owns_stream=True, compact=compact
        )
    if spec.startswith("jsonl="):
        return JsonLinesTransport(
            Path(spec.partition("=")[2]).open("a", encoding="utf-8"),
            owns_stream=True, compact=compact,
        )
    if spec.startswith("ws="):
        return WebSocketTransport(spec.partition("=")[2], compact=compact)
    if spec.startswith("ws://"):
        return WebSocketTransport(spec, compact=compact)
    raise ValueError(f"unknown transport spec: {spec}")
