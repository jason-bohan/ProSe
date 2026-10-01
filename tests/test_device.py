from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from prose.device import (
    ConsoleTransport,
    HudTransport,
    JsonLinesTransport,
    WebSocketTransport,
    frame_to_payload,
    open_transport,
)
from prose.hud import HudFrame, Objection, TranscriptLine
from prose.pipeline import SAMPLE_TRANSCRIPT, run


def make_frame(seq: int = 1) -> HudFrame:
    return HudFrame(
        seq=seq,
        transcript=TranscriptLine(speaker="Witness A", text="He said the fee was doubled."),
        objections=(
            Objection(
                rule_id="hearsay",
                label="Hearsay",
                citation="FRE 802",
                prompt="OBJECTION: HEARSAY (FRE 802)",
                hits=("he said",),
                confidence=0.65,
            ),
        ),
        prompt="OBJECTION: HEARSAY (FRE 802)",
    )


def test_console_transport_writes_formatted_frame() -> None:
    out = io.StringIO()
    transport = ConsoleTransport(out=out)
    transport.send(make_frame())
    text = out.getvalue()
    assert "#1 Witness A:" in text
    assert "OBJECTION  Hearsay (FRE 802)" in text
    assert "HUD PROMPT> OBJECTION: HEARSAY" in text


def test_json_lines_transport_emits_valid_jsonl() -> None:
    stream = io.StringIO()
    transport = JsonLinesTransport(stream)
    transport.send(make_frame())
    transport.send(make_frame(seq=2))
    lines = stream.getvalue().strip().splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[0])
    assert payload["seq"] == 1
    assert payload["speaker"] == "Witness A"
    assert payload["objections"][0]["rule"] == "hearsay"
    assert payload["prompt"] == "OBJECTION: HEARSAY (FRE 802)"


def test_frame_payload_shape() -> None:
    payload = frame_to_payload(make_frame())
    assert set(payload) == {"seq", "speaker", "transcript", "prompt", "objections"}
    assert payload["objections"][0]["confidence"] == 0.65


def test_open_transport_console() -> None:
    assert isinstance(open_transport("console"), ConsoleTransport)


def test_open_transport_unknown_spec_raises() -> None:
    with pytest.raises(ValueError):
        open_transport("bluetooth")


def test_open_transport_jsonl_file(tmp_path: Path) -> None:
    target = tmp_path / "hud.jsonl"
    transport = open_transport(f"jsonl={target}")
    assert isinstance(transport, JsonLinesTransport)
    transport.send(make_frame())
    transport.close()
    written = json.loads(target.read_text(encoding="utf-8").strip())
    assert written["seq"] == 1


def test_open_transport_ws_specs() -> None:
    assert isinstance(open_transport("ws=ws://127.0.0.1:9000"), WebSocketTransport)
    assert isinstance(open_transport("ws://127.0.0.1:9000"), WebSocketTransport)


def test_ws_transport_requires_websockets_package() -> None:
    try:
        import websockets  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("websockets installed; offline connection behavior not tested")
    transport = WebSocketTransport("ws://127.0.0.1:9999")
    with pytest.raises(RuntimeError, match="websockets"):
        transport.send(make_frame())


def test_pipeline_streams_frames_to_transport(tmp_path: Path) -> None:
    target = tmp_path / "hud.jsonl"
    result = run(transport=open_transport(f"jsonl={target}"))
    frames = [
        json.loads(line)
        for line in target.read_text(encoding="utf-8").strip().splitlines()
    ]
    assert len(frames) == len(SAMPLE_TRANSCRIPT)
    assert [f["seq"] for f in frames] == list(range(1, len(SAMPLE_TRANSCRIPT) + 1))
    assert result.total_violations == 3


def test_transport_close_is_noop_for_console() -> None:
    transport: HudTransport = ConsoleTransport(out=io.StringIO())
    transport.close()