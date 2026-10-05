"""HUD launcher: the mode menu on the glasses, driven by the phone controller.

The menu and the debate scoreboards are rendered as ordinary HUD frames, so
the web app, the phone relay, and the glasses all share one state without a
second protocol. Mood labels come from copilot.MOOD_LABELS; the lens draws a
distinct parametric face per label (calm and confident smile, tense wears
worried brows, defensive furrows, frustrated shouts, neutral is flat), and
the boxer face follows momentum (>= 65 grin, <= 35 dazed).
"""
from __future__ import annotations

from .copilot import TRAIT_POLES, TRAIT_SETS, ToneMatrix

MODES: tuple[dict, ...] = (
    {
        "id": "debate",
        "title": "Debate practice",
        "hint": "Rhetoric drill against an AI opponent.",
        "mood": "calm",
        "config": {
            "method": "listening",
            "vocabulary": True,
            "legal_review": False,
            "include_case_documents": False,
            "include_legal_context": False,
        },
    },
    {
        "id": "litigation",
        "title": "Litigation practice",
        "hint": "Argue a case against a legal-trained AI with your documents.",
        "mood": "tense",
        "config": {
            "method": "structure",
            "vocabulary": True,
            "legal_review": True,
            "include_case_documents": True,
            "include_legal_context": True,
        },
    },
)

# The personality matrix: each mode owns its own four bipolar 0-4 traits (see
# copilot.TRAIT_SETS). Touch surfaces drag two XY pads; the glasses adjusts the
# highlighted trait with up/down, changes trait with left/right, and flips the
# matrix mode with the scroll/page keys.
TONE_ENTRY: dict = {
    "id": "tone",
    "title": "Personality matrix",
    "hint": "Coaching style dials for debate and litigation.",
    "mood": "confident",
    "config": {},
}
ENTRIES: tuple[dict, ...] = MODES + (TONE_ENTRY,)

# Glasses accessory buttons (HOGP normalized keys mapped by gm_plugin.h).
GLASS_BUTTONS: tuple[str, ...] = (
    "up", "down", "left", "right", "select", "back", "home",
    "page_up", "page_down", "scroll_up", "scroll_down",
)


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


class Launcher:
    """Menu cursor shared by the phone controller and the glasses HUD."""

    def __init__(self) -> None:
        self.index = 0
        self.state = "menu"  # "menu", "setup", or "tone"
        self.mode = ""
        self.tones: dict[str, dict[str, int]] = {
            mode: ToneMatrix(mode).as_payload() for mode in TRAIT_SETS
        }
        self.tone_mode = "debate"  # which matrix the tone state is editing
        self.dial = 0

    @property
    def mode_config(self) -> dict:
        return dict(ENTRIES[self.index]["config"])

    def move(self, delta: int) -> None:
        step = 0 if delta == 0 else (1 if delta > 0 else -1)
        if self.state == "tone":
            if step:
                name = TRAIT_SETS[self.tone_mode][self.dial]
                values = dict(self.tones[self.tone_mode])
                values[name] = clamp(values[name] + step, 0, 4)
                self.tones[self.tone_mode] = values
            return
        self.index = (self.index + step) % len(ENTRIES)
        if self.state != "menu":
            self.state = "menu"
            self.mode = ""

    def dial_step(self, delta: int) -> None:
        """Left/right: move between the four traits in the tone state."""
        if self.state != "tone" or delta == 0:
            return
        step = 1 if delta > 0 else -1
        self.dial = (self.dial + step) % len(TRAIT_SETS[self.tone_mode])

    def set_mode(self, mode: str) -> None:
        """Switch which mode's matrix edits, from any state.

        The phone controller switches inside the tone screen, and the relay
        app's embedded pads switch before ever reaching it, so the choice is
        a plain preference rather than a tone-screen operation.
        """
        if mode not in TRAIT_SETS:
            raise ValueError("unknown personality mode")
        self.tone_mode = mode
        self.dial = min(self.dial, len(TRAIT_SETS[mode]) - 1)

    def select(self) -> dict:
        entry = ENTRIES[self.index]
        if self.state == "tone":
            self.dial = (self.dial + 1) % len(TRAIT_SETS[self.tone_mode])
            return entry
        if entry["id"] == "tone":
            self.state = "tone"
            self.mode = "tone"
            self.dial = 0
        else:
            self.state = "setup"
            self.mode = entry["id"]
            # Picking a mode primes the matrix for it, so configuring a debate
            # and then opening the matrix edits the debate matrix.
            self.tone_mode = entry["id"]
        return entry

    def back(self) -> None:
        self.state = "menu"
        self.mode = ""

    def press(self, button: str) -> None:
        """Map one glasses accessory button onto the current state's action."""
        if button not in GLASS_BUTTONS:
            raise ValueError("unknown glasses button")
        if self.state == "tone":
            if button == "up":
                self.move(1)
            elif button == "down":
                self.move(-1)
            elif button == "left":
                self.dial_step(-1)
            elif button == "right":
                self.dial_step(1)
            elif button == "select":
                self.select()
            elif button in ("scroll_up", "page_up"):
                self.set_mode("debate")
            elif button in ("scroll_down", "page_down"):
                self.set_mode("litigation")
            else:  # back, home
                self.back()
            return
        if self.state == "setup":
            # Mirrors the phone controller: nav/select do nothing in setup,
            # only leaving it works (home also rewinds the cursor).
            if button in ("back", "home"):
                self.back()
                if button == "home":
                    self.index = 0
            return
        if button in ("up", "left", "scroll_up"):
            self.move(-1)
        elif button in ("down", "right", "scroll_down"):
            self.move(1)
        elif button == "page_up":
            self.move(-3)
        elif button == "page_down":
            self.move(3)
        elif button == "select":
            self.select()
        else:  # back, home
            self.back()
            if button == "home":
                self.index = 0

    def set_tone(self, values: dict, mode: str | None = None) -> None:
        tone = ToneMatrix.from_dict(mode or self.tone_mode, values)
        self.tones[tone.mode] = tone.as_payload()

    def tone_for(self, mode: str) -> dict[str, int]:
        if mode not in TRAIT_SETS:
            raise ValueError("unknown personality mode")
        return dict(self.tones[mode])

    @property
    def tone_poles(self) -> dict[str, dict[str, list[str]]]:
        return {
            mode: {name: list(TRAIT_POLES[name]) for name in TRAIT_SETS[mode]}
            for mode in TRAIT_SETS
        }

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "index": self.index,
            "mode": self.mode,
            "modes": [
                {"id": m["id"], "title": m["title"], "hint": m["hint"],
                 "config": dict(m["config"])}
                for m in ENTRIES
            ],
            "tone": dict(self.tones[self.tone_mode]),
            "tone_mode": self.tone_mode,
            "tones": {mode: dict(values) for mode, values in self.tones.items()},
            "tone_poles": self.tone_poles,
            "dial": self.dial,
        }

    def payload(self) -> dict:
        """A glasses-ready frame describing the launcher's current state."""
        entry = ENTRIES[self.index]
        if self.state == "tone":
            traits = TRAIT_SETS[self.tone_mode]
            name = traits[self.dial]
            low, high = TRAIT_POLES[name]
            value = self.tones[self.tone_mode][name]
            bar = "[" + "#" * value + "-" * (4 - value) + "]"
            speaker = f"TONE {self.tone_mode}"
            prompt = f"{low} {bar} {high} {value}/4"
            transcript = " \N{MIDDLE DOT} ".join(
                f"{trait} {self.tones[self.tone_mode][trait]}" for trait in traits
            )
            mood = TONE_ENTRY["mood"]
            momentum = 50
        elif self.state == "setup":
            speaker = "SETUP"
            prompt = f"Open the phone controller to configure {entry['title']}"
            transcript = entry["hint"]
            mood = entry["mood"]
            momentum = 40 + self.index * 30
        elif entry["id"] == "tone":
            speaker = f"TONE {self.index + 1}/{len(ENTRIES)}"
            prompt = f"> {entry['title']} - pick on phone"
            transcript = entry["hint"]
            mood = entry["mood"]
            momentum = 50
        else:
            speaker = f"MODE {self.index + 1}/{len(MODES)}"
            prompt = f"> {entry['title']} - pick on phone"
            transcript = entry["hint"]
            mood = entry["mood"]
            momentum = 40 + self.index * 30
        return {
            "version": 2,
            "status": "ready",
            "speaker": speaker[:40],
            "transcript": transcript[:400],
            "prompt": prompt[:140],
            "mood_label": mood,
            "mood_intensity": 3,
            "momentum_pct": momentum,
            "expires_at": None,
            "hud": {"kind": "launcher", **self.snapshot()},
        }


class SessionScore:
    """Rolling confidence and opponent-face reactions for one debate session.

    Confidence only moves on deterministic signals already present in the
    session state, so the momentum bar is explainable on the phone: a focus
    word landing or a clearly longer substantiated reply pushes confidence up,
    an opponent blowout reply pushes it down.
    """

    HIT_WORD_BONUS = 8
    HIT_LENGTH_BONUS = 4
    BLOWOUT_PENALTY = 6
    MIN_MOMENTUM = 5
    MAX_MOMENTUM = 95

    def __init__(self, momentum: int = 50) -> None:
        self.momentum = clamp(momentum, self.MIN_MOMENTUM, self.MAX_MOMENTUM)
        self.words_used = 0
        self.hit = False
        self.delta = 0

    @staticmethod
    def _last(messages: list[dict], speaker: str) -> str:
        return next(
            (str(m.get("text", "")) for m in reversed(messages) if m.get("speaker") == speaker),
            "",
        )

    def turn(self, state: dict) -> dict:
        """Score the newest exchange and return the frame's hud extras."""
        messages = list(state.get("messages") or [])
        words = list(state.get("words_used") or [])
        delta = 0
        hit = False
        if len(words) > self.words_used:
            delta += self.HIT_WORD_BONUS
            hit = True
        self.words_used = len(words)
        mine = self._last(messages, "You")
        theirs = self._last(messages, "AI opponent")
        if mine and theirs:
            if len(theirs) >= max(240, int(len(mine) * 3 / 2)):
                delta -= self.BLOWOUT_PENALTY
            elif len(mine) >= int(len(theirs) * 7 / 5) + 40:
                delta += self.HIT_LENGTH_BONUS
                hit = True
        self.momentum = clamp(self.momentum + delta, self.MIN_MOMENTUM, self.MAX_MOMENTUM)
        self.hit = hit
        self.delta = delta
        return {"kind": "turn", "hit": hit, "delta": delta, "momentum": self.momentum}

    def mood(self) -> tuple[str, int]:
        """The opponent's face: visibly shaken after a good rebuttal."""
        if self.hit:
            return "frustrated", 5
        if self.momentum >= 65:
            return "tense", 3
        if self.momentum <= 35:
            return "confident", 3
        return "neutral", 2


def practice_frame(state: dict, score: SessionScore, kind: str, hud: dict) -> dict:
    """Build a glasses-ready frame from a practice session snapshot."""
    messages = list(state.get("messages") or [])
    coach = state.get("coach") or {}
    turn = int(state.get("turn") or 0)
    suggestion = str(coach.get("suggestion") or "")
    if kind == "start":
        speaker = "READY"
        transcript = str(state.get("config", {}).get("topic") or "Practice session")
        prompt = suggestion or "Opening suggestion ready on the phone."
    else:
        speaker = f"R{turn} OPPONENT"
        transcript = messages[-1].get("text", "") if messages else ""
        prompt = suggestion or "Your move - suggestions are on the phone."
    mood_label, mood_intensity = score.mood()
    return {
        "version": 2,
        "status": "ready",
        "speaker": speaker[:40],
        "transcript": transcript[:400],
        "prompt": prompt[:140],
        "mood_label": mood_label,
        "mood_intensity": mood_intensity,
        "momentum_pct": score.momentum,
        "expires_at": None,
        "hud": {"turn": turn, **hud},
    }
