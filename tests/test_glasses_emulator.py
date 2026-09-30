from __future__ import annotations

import contextlib
import itertools
import json
import threading
import time
from pathlib import Path

import pytest

from prose.glasses_emulator import (
    TerminalGlassesEmulator,
    consume_jsonl,
    consume_ws,
    format_frame_lines,
    render,
    strip_ansi,
)

FRAME = {
    "seq": 1,
    "speaker": "Witness A",
    "transcript": "He said the fee was doubled",
    "prompt": "OBJECTION: HEARSAY (FRE 802)",
    "objections": [
        {
            "rule": "hearsay",
            "label": "Hearsay",
            "citation": "FRE 802",
            "prompt": "OBJECTION: HEARSAY (FRE 802)",
            "hits": ["he said"],
            "confidence": 0.65,
        }
    ],
}

QUIET_FRAME = {
    "seq": 2,
    "speaker": "Court",
    "transcript": "Please continue.",
    "prompt": None,
    "objections": [],
}


def test_format_frame_lines_includes_speaker_transcript_and_objection() -> None:
    lines = [strip_ansi(line) for line in format_frame_lines(FRAME)]
    joined = " ".join(lines)
    assert "#1" in joined
    assert "Witness A:" in joined
    assert "He said the fee was doubled" in joined
    assert "OBJECTION" in joined
    assert "Hearsay (FRE 802)" in joined
    assert "conf=0.65" in joined
    assert "OBJECTION: HEARSAY (FRE 802)" in joined


def test_format_frame_lines_with_no_objections_or_prompt() -> None:
    lines = [strip_ansi(line) for line in format_frame_lines(QUIET_FRAME)]
    joined = " ".join(lines)
    assert "Court:" in joined
    assert "Please continue." in joined
    assert "OBJECTION" not in joined


def test_render_produces_a_bounded_box() -> None:
    screen = render([FRAME, QUIET_FRAME], width=78, height=20)
    lines = screen.splitlines()
    assert lines[0].startswith("┌─ LexGlasses HUD")
    assert lines[-1].startswith("└")
    assert all(len(strip_ansi(line)) == 78 for line in lines)
    plain = strip_ansi(screen)
    assert "Witness A" in plain
    assert "Court" in plain


def test_render_truncates_to_height() -> None:
    many_frames = [dict(FRAME, seq=i) for i in range(50)]
    screen = render(many_frames, width=78, height=5)
    # top + bottom border + at most `height` content rows
    assert len(screen.splitlines()) == 5 + 2


def test_terminal_emulator_feed_writes_to_given_stream() -> None:
    import io

    out = io.StringIO()
    emulator = TerminalGlassesEmulator(history=4, out=out)
    emulator.feed(FRAME)
    text = strip_ansi(out.getvalue())
    assert "Witness A" in text


def test_consume_jsonl_tails_new_lines_by_default(tmp_path: Path) -> None:
    path = tmp_path / "hud.jsonl"
    path.write_text(json.dumps(FRAME) + "\n", encoding="utf-8")

    gen = consume_jsonl(str(path), poll_interval=0.02, from_start=False)

    def append_more() -> None:
        time.sleep(0.1)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(QUIET_FRAME) + "\n")

    threading.Thread(target=append_more, daemon=True).start()
    frames = list(itertools.islice(gen, 1))
    assert frames == [QUIET_FRAME]  # existing line skipped, only the appended one seen


def test_consume_jsonl_from_start_replays_existing_lines(tmp_path: Path) -> None:
    path = tmp_path / "hud.jsonl"
    path.write_text(json.dumps(FRAME) + "\n" + json.dumps(QUIET_FRAME) + "\n", encoding="utf-8")

    gen = consume_jsonl(str(path), poll_interval=0.02, from_start=True)
    frames = list(itertools.islice(gen, 2))
    assert frames == [FRAME, QUIET_FRAME]


@pytest.fixture
def ws_frame_server():
    websockets = pytest.importorskip("websockets")
    import asyncio

    sent = [FRAME, QUIET_FRAME]
    ready = threading.Event()
    box: dict = {}

    def run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def handler(ws, *_args):
            for frame in sent:
                await ws.send(json.dumps(frame))

        async def main():
            server = await websockets.serve(handler, "127.0.0.1", 0)
            box["port"] = server.sockets[0].getsockname()[1]
            ready.set()
            await asyncio.Future()

        with contextlib.suppress(asyncio.CancelledError):
            loop.run_until_complete(main())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    ready.wait(timeout=5)
    yield f"ws://127.0.0.1:{box['port']}", sent


def test_consume_ws_yields_sent_frames(ws_frame_server) -> None:
    url, sent = ws_frame_server
    frames = list(itertools.islice(consume_ws(url), len(sent)))
    assert frames == sent
