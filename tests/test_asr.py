from __future__ import annotations

import pytest

from prose.asr import StreamingHudSession, StreamingTranscriber, VoskTranscriber
from prose.hud import HudSimulator


class FakeTranscriber(StreamingTranscriber):
    """Buffers chunks and finalizes on a sentinel b'|' chunk, standing in for
    a real ASR engine's silence/endpoint detection so the session-wiring
    logic can be tested without vosk or an audio fixture."""

    def __init__(self) -> None:
        self._buffer = b""

    def accept(self, chunk: bytes) -> str | None:
        if chunk == b"|":
            text = self._buffer.decode("utf-8").strip()
            self._buffer = b""
            return text or None
        self._buffer += chunk
        return None

    def flush(self) -> str | None:
        text = self._buffer.decode("utf-8").strip()
        self._buffer = b""
        return text or None


def test_session_returns_none_while_buffering() -> None:
    session = StreamingHudSession(FakeTranscriber())
    assert session.accept_audio(b"He said ") is None
    assert session.accept_audio(b"the fee was doubled") is None


def test_session_emits_frame_on_finalized_segment() -> None:
    session = StreamingHudSession(FakeTranscriber(), speaker="Witness A")
    session.accept_audio(b"He said the fee was doubled")
    frame = session.accept_audio(b"|")
    assert frame is not None
    assert frame.seq == 1
    assert frame.transcript.speaker == "Witness A"
    assert frame.transcript.text == "He said the fee was doubled"
    assert any(o.rule_id == "hearsay" for o in frame.objections)


def test_session_close_flushes_remaining_buffer() -> None:
    session = StreamingHudSession(FakeTranscriber())
    session.accept_audio(b"Isn't it true you signed the form")
    frame = session.close()
    assert frame is not None
    assert frame.transcript.text == "Isn't it true you signed the form"
    assert any(o.rule_id == "leading" for o in frame.objections)


def test_session_close_with_empty_buffer_returns_none() -> None:
    session = StreamingHudSession(FakeTranscriber())
    assert session.close() is None


def test_session_shares_simulator_frame_sequence_across_utterances() -> None:
    simulator = HudSimulator()
    session = StreamingHudSession(FakeTranscriber(), simulator=simulator)
    session.accept_audio(b"first utterance")
    session.accept_audio(b"|")
    session.accept_audio(b"second utterance")
    frame = session.accept_audio(b"|")
    assert frame.seq == 2
    assert len(simulator.frames) == 2


def test_vosk_transcriber_missing_dependency_message() -> None:
    try:
        import vosk  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("vosk installed; testing the not-installed error path elsewhere")
    with pytest.raises(RuntimeError, match="vosk"):
        VoskTranscriber("unused-model-path")
