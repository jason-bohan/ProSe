from __future__ import annotations

import abc
import json

from .hud import HudFrame, HudSimulator, TranscriptLine


class StreamingTranscriber(abc.ABC):
    """Consumes raw PCM16 mono audio chunks, emits finalized text segments.

    Mirrors how real streaming ASR engines (Vosk, whisper.cpp streaming,
    cloud streaming APIs) work: you feed small chunks continuously and only
    get text back once the engine decides an utterance boundary was hit
    (silence, endpointing). Everything in between returns None.
    """

    @abc.abstractmethod
    def accept(self, chunk: bytes) -> str | None:
        """Feed one chunk of audio. Returns finalized text once an utterance
        boundary is detected, else None (still buffering)."""

    def flush(self) -> str | None:
        """Force-finalize any buffered audio, e.g. at end of stream."""
        return None


class VoskTranscriber(StreamingTranscriber):
    """Offline streaming ASR via Vosk.

    Requires ``pip install vosk`` and a downloaded model directory (e.g.
    vosk-model-small-en-us-0.15 from https://alphacephei.com/vosk/models).
    Deliberately not a hard dependency: MockASR (prose/hud.py) keeps the
    text-only pipeline and its tests fully offline and download-free.
    """

    def __init__(self, model_path: str, sample_rate: int = 16000) -> None:
        try:
            import vosk
        except ImportError as exc:
            raise RuntimeError(
                "VoskTranscriber requires the 'vosk' package (pip install vosk) "
                "and a downloaded model directory"
            ) from exc
        vosk.SetLogLevel(-1)
        self._recognizer = vosk.KaldiRecognizer(vosk.Model(model_path), sample_rate)

    def accept(self, chunk: bytes) -> str | None:
        if self._recognizer.AcceptWaveform(chunk):
            text = json.loads(self._recognizer.Result()).get("text", "").strip()
            return text or None
        return None

    def flush(self) -> str | None:
        text = json.loads(self._recognizer.FinalResult()).get("text", "").strip()
        return text or None


class StreamingHudSession:
    """Wires a StreamingTranscriber to a HudSimulator: feed audio in, get a
    HudFrame out each time the transcriber finalizes an utterance. This is
    the real-audio counterpart to HudSimulator.feed_lines (pre-scripted
    text) and prose.pipeline.run's SAMPLE_TRANSCRIPT demo."""

    def __init__(
        self,
        transcriber: StreamingTranscriber,
        simulator: HudSimulator | None = None,
        speaker: str = "Speaker",
    ) -> None:
        self.transcriber = transcriber
        self.simulator = simulator or HudSimulator()
        self.speaker = speaker

    def accept_audio(self, chunk: bytes) -> HudFrame | None:
        text = self.transcriber.accept(chunk)
        if not text:
            return None
        return self.simulator.feed_transcript(TranscriptLine(self.speaker, text))

    def close(self) -> HudFrame | None:
        text = self.transcriber.flush()
        if not text:
            return None
        return self.simulator.feed_transcript(TranscriptLine(self.speaker, text))
