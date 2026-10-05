from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

PRIORITY: dict[str, int] = {"objection": 0, "statute": 1, "procedural": 2, "note": 3}


@dataclass(frozen=True)
class Objection:
    rule_id: str
    label: str
    citation: str
    prompt: str
    hits: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class TranscriptLine:
    speaker: str
    text: str


@dataclass(frozen=True)
class HudCue:
    mode: str
    kind: str
    headline: str
    say: str
    rationale: str
    next_question: str
    caveat: str
    mood_label: str = ""
    mood_intensity: int = 0
    momentum_signal: int = 0
    sources: tuple[dict, ...] = ()


@dataclass(frozen=True)
class HudFrame:
    seq: int
    transcript: TranscriptLine
    objections: tuple[Objection, ...]
    prompt: str | None
    cue: HudCue | None = None
    status: str | None = None
    turn_id: int | None = None
    latency_ms: int | None = None
    error: str = ""
    expires_at: float | None = None
    legal_review: dict | None = None
    momentum_pct: int | None = None


def load_rules() -> tuple[dict, ...]:
    with (DATA_DIR / "objections.json").open(encoding="utf-8") as fh:
        return tuple(json.load(fh))


class ObjectionEngine:
    def __init__(self, rules: tuple[dict, ...] | None = None) -> None:
        self.rules = rules if rules is not None else load_rules()

    def evaluate(self, text: str) -> list[Objection]:
        lowered = text.lower()
        found: list[Objection] = []
        for rule in self.rules:
            hits = tuple(t for t in rule["triggers"] if t in lowered)
            if len(hits) >= int(rule.get("min_hits", 1)):
                confidence = min(1.0, 0.5 + 0.15 * len(hits))
                found.append(
                    Objection(
                        rule_id=rule["id"],
                        label=rule["label"],
                        citation=rule["citation"],
                        prompt=rule["prompt"],
                        hits=hits,
                        confidence=confidence,
                    )
                )
        return found


class Teleprompter:
    def __init__(self, window: int = 4) -> None:
        self._window = window
        self._items: list[tuple[int, int, str]] = []
        self._seq = 0

    def add(self, text: str, priority: str = "note") -> None:
        self._seq += 1
        self._items.append((PRIORITY.get(priority, 3), self._seq, text))
        self._items.sort(key=lambda item: (item[0], item[1]))
        del self._items[self._window :]

    def render(self) -> list[str]:
        return [item[2] for item in self._items]

    def pop(self) -> str | None:
        if not self._items:
            return None
        return self._items.pop(0)[2]

    def clear(self) -> None:
        self._items.clear()


class MockASR:
    """Whisper-compatible stand-in; swap for a real ASR backend (whisper.cpp / API)."""

    def transcribe(self, utterance: str) -> TranscriptLine:
        speaker, _, text = utterance.partition(": ")
        return TranscriptLine(speaker.strip() or "speaker", text.strip())


class HudSimulator:
    def __init__(self) -> None:
        self.engine = ObjectionEngine()
        self.asr = MockASR()
        self.prompter = Teleprompter()
        self.frames: list[HudFrame] = []

    def feed(self, utterance: str) -> HudFrame:
        return self.feed_transcript(self.asr.transcribe(utterance))

    def feed_transcript(self, line: TranscriptLine) -> HudFrame:
        """Push an already-transcribed line (e.g. a finalized segment from a
        live streaming ASR backend) straight into the objection engine,
        bypassing MockASR's "Speaker: text" parsing."""
        objections = tuple(self.engine.evaluate(line.text))
        for objection in objections:
            self.prompter.add(objection.prompt, "objection")
        frame = HudFrame(len(self.frames) + 1, line, objections, self.prompter.pop())
        self.frames.append(frame)
        return frame

    def feed_lines(self, lines: list[str]) -> list[HudFrame]:
        return [self.feed(line) for line in lines]
