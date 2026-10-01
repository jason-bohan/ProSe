"""Terminal-based smart-glasses HUD emulator.

The fastest/lightest way to see prose/device.py's frame stream rendered as
something resembling a monochrome AR waveguide display: no GUI toolkit, no
browser, stdlib + ANSI escape codes only. Instant startup, near-zero CPU/
memory, works over SSH. Plays the role of the "companion app" real hardware
(Brilliant Labs Frame, OpenGlass, HoloLens) would run -- prose/device.py only
ships HudFrame JSON to a transport; this is what finally draws it.

    prose.cli glasses --jsonl hud.jsonl     # tail a jsonl transport's output
    prose.cli glasses --ws ws://host:port   # connect as a client to a ws= transport
"""

from __future__ import annotations

import json
import re
import textwrap
import time
from collections import deque
from collections.abc import Iterator
from pathlib import Path

CLEAR_HOME = "\x1b[2J\x1b[H"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
BOLD = "\x1b[1m"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def format_frame_lines(frame: dict, width: int = 72) -> list[str]:
    """Render one HudFrame payload (see prose.device.frame_to_payload) as the
    lines a monochrome waveguide display would show for it."""
    lines: list[str] = []
    header = f"{DIM}#{frame['seq']}{RESET} {BOLD}{frame['speaker']}:{RESET} {frame['transcript']}"
    lines.extend(textwrap.wrap(header, width=width, subsequent_indent="    ") or [header])
    for objection in frame.get("objections", ()):
        text = (
            f"{RED}⚠ OBJECTION{RESET} {objection['label']} ({objection['citation']}) "
            f"conf={objection['confidence']:.2f}"
        )
        lines.extend(textwrap.wrap(text, width=width, subsequent_indent="    "))
    if frame.get("prompt"):
        text = f"{GREEN}› {frame['prompt']}{RESET}"
        lines.extend(textwrap.wrap(text, width=width, subsequent_indent="    "))
    return lines


def render(frames: list[dict], width: int = 78, height: int = 20) -> str:
    """Build the full boxed HUD screen for a rolling window of frames, most
    recent last. Truncated from the top to fit `height` content rows."""
    body: list[str] = []
    for frame in frames:
        if body:
            body.append("")
        body.extend(format_frame_lines(frame, width=width - 4))
    body = body[-height:] if len(body) > height else body

    top = "┌─ LexGlasses HUD " + "─" * max(0, width - 19) + "┐"
    bottom = "└" + "─" * (width - 2) + "┘"
    rows = [top]
    for line in body:
        visible_len = len(strip_ansi(line))
        padding = max(0, (width - 4) - visible_len)
        rows.append(f"│ {line}{' ' * padding} │")
    for _ in range(height - len(body)):
        rows.append(f"│{' ' * (width - 2)}│")
    rows.append(bottom)
    return "\n".join(rows)


class TerminalGlassesEmulator:
    def __init__(self, history: int = 8, width: int = 78, height: int = 20, out=None) -> None:
        self._frames: deque[dict] = deque(maxlen=history)
        self.width = width
        self.height = height
        if out is None:
            import sys

            out = sys.stdout
            # Windows consoles often default stdout to a legacy codepage (e.g.
            # cp1252) that can't encode the box-drawing/warning glyphs; fall
            # back to '?' substitution instead of crashing mid-stream.
            reconfigure = getattr(out, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(errors="replace")
        self._out = out

    def feed(self, frame: dict) -> None:
        self._frames.append(frame)
        out = self._out
        out.write(CLEAR_HOME)
        out.write(render(list(self._frames), width=self.width, height=self.height))
        out.write("\n")
        out.flush()


def consume_jsonl(
    path: str, poll_interval: float = 0.1, from_start: bool = False
) -> Iterator[dict]:
    """Tail a jsonl HUD transport's output file, yielding parsed frames as
    they appear. Runs until the caller stops iterating."""
    file_path = Path(path)
    while not file_path.exists():
        time.sleep(poll_interval)
    with file_path.open("r", encoding="utf-8") as fh:
        if not from_start:
            fh.seek(0, 2)
        while True:
            line = fh.readline()
            if not line:
                time.sleep(poll_interval)
                continue
            line = line.strip()
            if line:
                yield json.loads(line)


def consume_ws(url: str) -> Iterator[dict]:
    """Connect as a WebSocket client to a ws= HUD transport, yielding parsed
    frames as they arrive. Runs until the connection closes."""
    import asyncio

    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError(
            "consume_ws requires the 'websockets' package (pip install websockets)"
        ) from exc

    async def _iter():
        async with websockets.connect(url) as ws:
            async for message in ws:
                yield json.loads(message)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    agen = _iter()
    try:
        while True:
            try:
                yield loop.run_until_complete(agen.__anext__())
            except StopAsyncIteration:
                return
    finally:
        loop.run_until_complete(agen.aclose())
        loop.close()
