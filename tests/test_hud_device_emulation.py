"""Emulation tests for the smart-glasses HUD link: drive prose.device's real
WebSocketTransport against a local "glasses" receiver instead of an in-memory
StringIO, so the full serialize -> socket -> deserialize path is exercised.

No physical headset/SDK is required -- tests/emulation/device_emulator.py
plays the role of the companion app that would sit on real hardware
(Vuzix/HoloLens/Brilliant Labs), consistent with this project's stdlib-only
design (prose/device.py already treats jsonl/ws as generic bridges to any
BLE/USB-tethered glasses).
"""

from __future__ import annotations

import pytest

pytest.importorskip("websockets")

from prose.device import WebSocketTransport  # noqa: E402
from prose.pipeline import SAMPLE_TRANSCRIPT, run  # noqa: E402
from tests.emulation.device_emulator import GlassesEmulator  # noqa: E402


def test_glasses_emulator_receives_streamed_frames() -> None:
    with GlassesEmulator() as glasses:
        transport = WebSocketTransport(glasses.url)
        result = run(transport=transport)

        received = glasses.wait_for_count(len(SAMPLE_TRANSCRIPT))
        assert len(received) == len(SAMPLE_TRANSCRIPT)
        assert [f["seq"] for f in received] == list(range(1, len(SAMPLE_TRANSCRIPT) + 1))
        assert received == [
            {
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
            for frame in result.frames
        ]


def test_glasses_emulator_sees_courtroom_objections_live() -> None:
    with GlassesEmulator() as glasses:
        transport = WebSocketTransport(glasses.url)
        run(transport=transport)

        received = glasses.wait_for_count(len(SAMPLE_TRANSCRIPT))
        fired_rule_ids = {o["rule"] for frame in received for o in frame["objections"]}
        assert "hearsay" in fired_rule_ids
        assert "leading" in fired_rule_ids
        assert "speculation" in fired_rule_ids


def test_multiple_sessions_against_the_same_emulator_are_independent() -> None:
    with GlassesEmulator() as glasses:
        run(transport=WebSocketTransport(glasses.url), transcript=SAMPLE_TRANSCRIPT[:1])
        run(transport=WebSocketTransport(glasses.url), transcript=SAMPLE_TRANSCRIPT[:2])
        assert len(glasses.wait_for_count(1 + 2)) == 1 + 2
