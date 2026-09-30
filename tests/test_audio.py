from __future__ import annotations

import itertools
import sys
import wave
from pathlib import Path

import pytest

from prose.audio import MicrophoneSource, WavFileSource


def _write_wav(path: Path, *, channels: int = 1, sampwidth: int = 2, framerate: int = 16000,
                n_frames: int = 4000) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sampwidth)
        wav_file.setframerate(framerate)
        wav_file.writeframes(b"\x00" * n_frames * sampwidth * channels)


def test_wav_file_source_yields_correctly_sized_chunks(tmp_path: Path) -> None:
    path = tmp_path / "sample.wav"
    _write_wav(path, framerate=16000, n_frames=4000)  # 250ms exactly
    source = WavFileSource(str(path), chunk_ms=250)
    assert source.sample_rate == 16000
    chunks = list(source.chunks())
    source.close()
    assert len(chunks) == 1
    assert len(chunks[0]) == 4000 * 2  # 16-bit samples


def test_wav_file_source_yields_multiple_chunks_for_longer_audio(tmp_path: Path) -> None:
    path = tmp_path / "sample.wav"
    _write_wav(path, framerate=16000, n_frames=10000)  # 625ms -> 3 chunks of 250ms
    source = WavFileSource(str(path), chunk_ms=250)
    chunks = list(source.chunks())
    source.close()
    assert len(chunks) == 3
    assert sum(len(c) for c in chunks) == 10000 * 2


def test_wav_file_source_rejects_stereo(tmp_path: Path) -> None:
    path = tmp_path / "stereo.wav"
    _write_wav(path, channels=2)
    with pytest.raises(ValueError, match="mono"):
        WavFileSource(str(path))


def test_wav_file_source_rejects_non_16_bit(tmp_path: Path) -> None:
    path = tmp_path / "8bit.wav"
    _write_wav(path, sampwidth=1)
    with pytest.raises(ValueError, match="16-bit"):
        WavFileSource(str(path))


class FakeStream:
    """Stands in for sounddevice.RawInputStream so tests never open the real
    microphone (no OS permission prompt, no recorded ambient audio)."""

    def __init__(self, chunk_bytes: bytes) -> None:
        self.chunk_bytes = chunk_bytes
        self.read_calls = 0
        self.stopped = False
        self.closed = False

    def read(self, _frames: int) -> tuple[bytes, bool]:
        self.read_calls += 1
        return self.chunk_bytes, False

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


def test_microphone_source_streams_indefinitely_from_fake_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeStream(b"\x00\x01" * 100)
    monkeypatch.setattr("prose.audio._open_raw_input_stream", lambda *a, **k: fake)
    source = MicrophoneSource(sample_rate=16000, chunk_ms=250)
    first_five = list(itertools.islice(source.chunks(), 5))
    source.close()
    assert len(first_five) == 5
    assert all(chunk == fake.chunk_bytes for chunk in first_five)
    assert fake.stopped and fake.closed


def test_microphone_source_raises_clear_error_when_sounddevice_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    with pytest.raises(RuntimeError, match="sounddevice"):
        MicrophoneSource()
