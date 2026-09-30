from __future__ import annotations

import abc
import wave
from collections.abc import Iterator


class AudioSource(abc.ABC):
    """Yields raw 16-bit mono PCM chunks at a fixed sample rate -- the input
    side of prose/asr.py's StreamingTranscriber. A file and a live
    microphone implement the same interface so prose.cli listen can drive
    either through the identical accept_audio() loop."""

    sample_rate: int

    @abc.abstractmethod
    def chunks(self) -> Iterator[bytes]:
        """Yield audio chunks. May be finite (a file, exhausted) or run
        until the caller stops iterating (a live microphone)."""

    def close(self) -> None:
        return None


class WavFileSource(AudioSource):
    def __init__(self, path: str, chunk_ms: int = 250) -> None:
        self._wav = wave.open(path, "rb")  # noqa: SIM115 -- held open across chunks()/close()
        if self._wav.getsampwidth() != 2 or self._wav.getnchannels() != 1:
            self._wav.close()
            raise ValueError(f"{path}: listen requires a 16-bit mono PCM WAV file")
        self.sample_rate = self._wav.getframerate()
        self._chunk_frames = max(1, self.sample_rate * chunk_ms // 1000)

    def chunks(self) -> Iterator[bytes]:
        while chunk := self._wav.readframes(self._chunk_frames):
            yield chunk

    def close(self) -> None:
        self._wav.close()


def _open_raw_input_stream(sample_rate: int, blocksize: int, device: int | str | None):
    """Isolated so tests can monkeypatch stream creation instead of opening
    a real microphone (which would record actual ambient audio and, on
    Windows, trigger an OS mic-permission prompt)."""
    import sounddevice as sd

    stream = sd.RawInputStream(
        samplerate=sample_rate, channels=1, dtype="int16", blocksize=blocksize, device=device
    )
    stream.start()
    return stream


class MicrophoneSource(AudioSource):
    """Live capture from a local input device via the 'sounddevice' package
    (pip install ".[glasses]"). Runs until the caller stops iterating
    chunks() -- there's no natural end-of-stream for a live mic."""

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_ms: int = 250,
        device: int | str | None = None,
    ) -> None:
        try:
            import sounddevice  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "MicrophoneSource requires the 'sounddevice' package (pip install sounddevice)"
            ) from exc
        self.sample_rate = sample_rate
        self._chunk_frames = max(1, sample_rate * chunk_ms // 1000)
        self._stream = _open_raw_input_stream(sample_rate, self._chunk_frames, device)

    def chunks(self) -> Iterator[bytes]:
        while True:
            data, _overflowed = self._stream.read(self._chunk_frames)
            yield bytes(data)

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()
