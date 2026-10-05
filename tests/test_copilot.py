from __future__ import annotations

import io
import json
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from prose.copilot import (
    CopilotError,
    CopilotSession,
    ModelCoach,
    ModelSettings,
    SessionConfig,
    SourceNote,
    ToneMatrix,
    courtroom_sources,
    parse_cue,
    rate_limit_message,
)
from prose.device import JsonLinesTransport, frame_to_glasses_payload, frame_to_payload
from prose.glasses_emulator import TerminalGlassesEmulator
from prose.hud import TranscriptLine
from prose.web import build_site


def answer(**changes):
    return {"kind": "question", "headline": "Ask what evidence supports the claim.",
            "say": "What evidence supports that conclusion?", "rationale": "No evidence cited.",
            "next_question": "", "caveat": "", "source_ids": [],
            "speaker_mood": {"label": "neutral", "intensity": 3}, "momentum_signal": 0,
            **changes}


class FakeCoach:
    def respond(self, config, turns, sources, tone):
        return answer()


def test_audio_turns_are_nonblocking_and_stale_answers_are_discarded():
    entered, release = threading.Event(), threading.Event()
    calls = []

    class SlowCoach:
        def respond(self, config, turns, sources, tone):
            calls.append(turns)
            if len(calls) == 1:
                entered.set()
                assert release.wait(3)
            return answer(headline=turns[-1]["text"])

    session = CopilotSession(SessionConfig(), SlowCoach(), debounce=0)
    try:
        first = session.feed_transcript(TranscriptLine("Opponent", "Old claim"))
        assert first.status == "thinking" and first.prompt is None
        assert entered.wait(2)
        # This call must finish while the provider is still blocked.
        session.feed_transcript(TranscriptLine("Wearer", "My clarification"))
        latest = session.feed_transcript(TranscriptLine("Opponent", "Revised claim"))
        assert latest.turn_id == 3 and not release.is_set()
        release.set()
        assert session.wait_idle(3)
        ready = [f for f in session.frames_after() if f.cue]
        assert len(ready) == 1
        assert ready[0].turn_id == 3
        assert ready[0].cue.headline == "Revised claim"
        assert len(calls) == 2  # intermediate pending request was coalesced
        assert len(calls[-1]) == 3  # but its conversational context was retained
    finally:
        release.set()
        session.close()


def test_provider_failure_keeps_transcript_live_and_clears_prompt():
    class FailingCoach:
        def respond(self, config, turns, sources, tone):
            raise RuntimeError("secret provider internals")

    session = CopilotSession(SessionConfig(), FailingCoach(), debounce=0)
    try:
        for text in ("First", "Second"):
            session.feed_transcript(TranscriptLine("Opponent", text))
            assert session.wait_idle(2)
            frame = session.frames_after()[-1]
            assert frame.status == "unavailable" and frame.prompt is None
            assert "secret" not in frame.error
        assert frame.turn_id == 2
    finally:
        session.close()


def test_stopping_prevents_inflight_cue_delivery():
    entered, release = threading.Event(), threading.Event()

    class BlockedCoach:
        def respond(self, config, turns, sources, tone):
            entered.set()
            release.wait(3)
            return answer()

    session = CopilotSession(SessionConfig(), BlockedCoach(), debounce=0)
    session.feed_transcript(TranscriptLine("Opponent", "Claim"))
    assert entered.wait(2)
    session.close()
    release.set()
    session._worker.join(2)
    assert len(session.frames_after()) == 1
    with pytest.raises(ValueError, match="stopped"):
        session.feed_transcript(TranscriptLine("Opponent", "Another claim"))


def test_late_answers_expire_instead_of_becoming_actionable():
    session = CopilotSession(SessionConfig(), FakeCoach(), debounce=0, max_age=0)
    try:
        session.feed_transcript(TranscriptLine("Opponent", "Claim"))
        assert session.wait_idle(2)
        frame = session.frames_after()[-1]
        assert frame.status == "expired" and frame.prompt is None
    finally:
        session.close()


def test_display_expiration_emits_a_clearing_frame():
    session = CopilotSession(SessionConfig(), FakeCoach(), debounce=0)
    try:
        session.feed_transcript(TranscriptLine("Opponent", "Claim"))
        assert session.wait_idle(2)
        ready = session.frames_after()[-1]
        assert ready.expires_at > time.time()
        with session._condition:
            session._cue_deadline = time.monotonic() - 1
        clearing = session.frames_after(ready.seq)[-1]
        assert clearing.status == "listening" and clearing.prompt is None
    finally:
        session.close()


def test_phone_bridge_payload_excludes_private_context_and_stays_small():
    session = CopilotSession(SessionConfig(notes="Private case notes"), FakeCoach(), debounce=0)
    try:
        session.feed_transcript(TranscriptLine("Opponent", "Private transcript"))
        assert session.wait_idle(2)
        frame = session.frames_after()[-1]
        payload = frame_to_glasses_payload(frame)
        encoded = json.dumps(payload)
        assert len(encoded.encode()) < 1024
        assert "Private" not in encoded and "rationale" not in encoded
        assert payload["prompt"] == frame.prompt and payload["expires_at"] == frame.expires_at
        out = io.StringIO()
        JsonLinesTransport(out, compact=True).send(frame)
        assert json.loads(out.getvalue()) == payload
    finally:
        session.close()


@pytest.mark.parametrize("changes", [
    {"kind": "objection"}, {"source_ids": ["INVENTED-CASE"]},
    {"source_ids": "FRE-611"}, {"headline": "x" * 121}, {"kind": "not-a-cue"},
    {"speaker_mood": {"label": "angry", "intensity": 3}},
    {"speaker_mood": {"label": "calm", "intensity": 6}},
    {"speaker_mood": {"label": "calm", "intensity": "3"}},
    {"speaker_mood": None}, {"momentum_signal": 5}, {"momentum_signal": None},
])
def test_unsubstantiated_or_invalid_cues_are_rejected(changes):
    with pytest.raises(CopilotError):
        parse_cue(answer(**changes), SessionConfig(), ())


def test_mood_and_momentum_tolerate_whole_number_floats_from_the_model():
    # LLM JSON generation isn't always consistent about int vs float formatting
    # (e.g. 3.0 instead of 3); a whole-number float should still be accepted.
    cue = parse_cue(answer(speaker_mood={"label": "tense", "intensity": 4.0},
                           momentum_signal=-1.0), SessionConfig(), ())
    assert cue.mood_intensity == 4 and cue.momentum_signal == -1
    with pytest.raises(CopilotError):
        parse_cue(answer(speaker_mood={"label": "tense", "intensity": 4.5}),
                  SessionConfig(), ())
    with pytest.raises(CopilotError):
        parse_cue(answer(speaker_mood={"label": "tense", "intensity": True}),
                  SessionConfig(), ())


def test_mood_and_momentum_are_carried_even_without_a_cue():
    cue = parse_cue(answer(kind="none"), SessionConfig(), ())
    assert cue.headline == "" and cue.mood_label == "neutral" and cue.mood_intensity == 3
    assert cue.momentum_signal == 0
    tense = parse_cue(answer(speaker_mood={"label": "tense", "intensity": 5},
                             momentum_signal=-2), SessionConfig(), ())
    assert tense.mood_label == "tense" and tense.mood_intensity == 5
    assert tense.momentum_signal == -2


def test_set_tone_applies_to_next_snapshot_and_rejects_bad_input():
    session = CopilotSession(SessionConfig(), FakeCoach(), debounce=0)
    try:
        assert session._tone == ToneMatrix("debate")
        updated = session.set_tone({"humor": 4, "rhetoric": 1})
        assert updated == ToneMatrix("debate", (4, 1, 2, 2))
        assert session._tone == updated
        with pytest.raises(ValueError):
            session.set_tone({"humor": 9})
        with pytest.raises(ValueError):
            session.set_tone({"directness": 3})  # a litigation trait, not a debate one
        assert session._tone == updated  # a rejected update must not disturb the prior tone
    finally:
        session.close()
    with pytest.raises(ValueError, match="stopped"):
        session.set_tone({"humor": 1})


def test_authorities_are_scoped_and_evidence_is_not_treated_as_law():
    federal = SessionConfig(mode="litigation", jurisdiction="US federal", stage="cross")
    sources = courtroom_sources(federal)
    assert sources and all(s.authority for s in sources)
    cue = parse_cue(answer(kind="objection", source_ids=["FRE-602"]), federal, sources)
    assert cue.sources[0]["id"] == "FRE-602"
    assert courtroom_sources(SessionConfig(mode="litigation", jurisdiction="Indiana")) == ()
    assert courtroom_sources(SessionConfig(mode="debate", jurisdiction="US federal")) == ()
    with pytest.raises(CopilotError, match="authority"):
        parse_cue(answer(kind="objection", source_ids=["EXHIBIT"]), federal,
                  (SourceNote("EXHIBIT", "Witness account", "A party's allegation"),))


def test_credentials_never_fall_back_to_an_unrelated_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "secret-gemini-key")
    monkeypatch.delenv("PROSE_AI_API_KEY", raising=False)
    monkeypatch.setenv("PROSE_AI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("PROSE_AI_MODEL", "local-model")
    with pytest.raises(CopilotError, match="PROSE_AI_API_KEY"):
        ModelSettings.from_env()
    monkeypatch.setenv("PROSE_AI_BASE_URL", "http://127.0.0.1:11434/v1")
    settings = ModelSettings.from_env()
    assert settings.api_key == ""
    assert "secret" not in repr(settings)
    monkeypatch.setenv("PROSE_AI_BASE_URL", "http://external.test/v1")
    with pytest.raises(CopilotError, match="HTTPS"):
        ModelSettings.from_env()


@contextmanager
def model_server(result=None, *, finish_reason="stop", status=200):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            payload = {"choices": [{"finish_reason": finish_reason,
                                    "message": {"content": json.dumps(result or answer())}}]}
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize("finish_reason,status", [("length", 200), ("stop", 429)])
def test_truncated_and_rate_limited_model_responses_fail_cleanly(finish_reason, status):
    with model_server(finish_reason=finish_reason, status=status) as (url, _):
        coach = ModelCoach(ModelSettings(url, "test-model", "do-not-leak"))
        with pytest.raises(CopilotError) as exc:
            coach.respond(SessionConfig(), [], (), ToneMatrix())
        assert "do-not-leak" not in str(exc.value)


def test_practice_completion_budget_and_timeout_preserve_hud_defaults(monkeypatch):
    monkeypatch.setenv("PROSE_AI_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("PROSE_AI_MODEL", "test-model")
    monkeypatch.delenv("PROSE_AI_TIMEOUT", raising=False)
    assert ModelSettings.from_env().timeout == 12
    assert ModelSettings.from_env(default_timeout=30).timeout == 30
    monkeypatch.setenv("PROSE_AI_TIMEOUT", "20")
    assert ModelSettings.from_env(default_timeout=30).timeout == 20
    with model_server() as (url, calls):
        settings = ModelSettings(url, "test-model")
        ModelCoach(settings).complete_json("HUD", {})
        ModelCoach(settings, max_completion_tokens=4096).complete_json("Practice", {})
        assert [call["max_completion_tokens"] for call in calls] == [2048, 4096]


@pytest.mark.parametrize("as_list", [False, True])
def test_daily_quota_takes_priority_over_short_retry_delay(as_list):
    payload = {"error": {"message": "private-key-do-not-echo", "details": [
        {"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
                         "quotaValue": "20"}]}, {"retryDelay": "20s"},
    ]}}
    if as_list:
        payload = [payload]
    error = urllib.error.HTTPError("https://example.test", 429, "quota", {},
                                   io.BytesIO(json.dumps(payload).encode()))
    message = rate_limit_message(error, "https://generativelanguage.googleapis.com/v1beta/openai")
    assert "20 requests/day" in message and "midnight Pacific" in message
    assert "private-key" not in message and "20s" not in message


def test_malformed_rate_limit_response_has_safe_fallback():
    error = urllib.error.HTTPError("https://example.test", 429, "quota", {},
                                   io.BytesIO(b"private-key-do-not-echo"))
    message = rate_limit_message(error, "https://example.test")
    assert "HTTP 429" in message and "private-key" not in message


def test_explicit_groq_provider_uses_its_key_and_model(monkeypatch):
    monkeypatch.setenv("PROSE_AI_PROVIDER", "groq")
    for name in ("PROSE_AI_BASE_URL", "PROSE_AI_MODEL", "PROSE_AI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-private")
    monkeypatch.setenv("GROQ_API_KEY", "groq-private")
    settings = ModelSettings.from_env()
    assert settings.base_url == "https://api.groq.com/openai/v1"
    assert settings.model == "openai/gpt-oss-120b" and settings.api_key == "groq-private"
    assert "private" not in json.dumps(settings.public_status())
    monkeypatch.delenv("GROQ_API_KEY")
    with pytest.raises(CopilotError, match="PROSE_AI_API_KEY"):
        ModelSettings.from_env()


def test_conflicting_provider_url_is_rejected(monkeypatch):
    monkeypatch.setenv("PROSE_AI_PROVIDER", "groq")
    monkeypatch.setenv("PROSE_AI_BASE_URL", "https://example.test/v1")
    with pytest.raises(CopilotError, match="conflicts"):
        ModelSettings.from_env()


def test_live_coach_http_session_sse_and_device_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("PROSE_DATA_DIR", str(tmp_path))
    with model_server() as (model_url, calls):
        monkeypatch.setenv("PROSE_AI_BASE_URL", model_url)
        monkeypatch.setenv("PROSE_AI_MODEL", "test-model")
        monkeypatch.delenv("PROSE_AI_API_KEY", raising=False)
        site = build_site("127.0.0.1", 0)
        thread = threading.Thread(target=site.start, daemon=True)
        thread.start()

        def post(path, data, headers=None):
            request = urllib.request.Request(
                site.url + path, json.dumps(data).encode(),
                {"Content-Type": "application/json", **(headers or {})},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                return json.load(response)

        try:
            with urllib.request.urlopen(site.url + "/copilot") as response:
                page = response.read().decode()
            assert "Debate coach" in page and "Litigation coach" in page
            assert "test-model" in page
            for invalid, code in [([], 400), ({"mode": "unknown"}, 400),
                                  ({"document_ids": ["missing"]}, 400)]:
                with pytest.raises(urllib.error.HTTPError) as exc:
                    post("/api/copilot/sessions", invalid)
                assert exc.value.code == code
            with pytest.raises(urllib.error.HTTPError) as exc:
                post("/api/copilot/sessions", {}, {"Origin": "https://external.test"})
            assert exc.value.code == 403
            created = post("/api/copilot/sessions", {"mode": "debate", "goal": "Discuss transport"})
            session_id = created["session_id"]
            session = site.app.copilot.get(session_id)
            # A new session is primed with the launcher's debate matrix.
            assert session._tone.as_payload() == site.app.launcher.tone_for("debate")
            toned = post("/api/copilot/tone", {"session_id": session_id,
                                               "tone": {"humor": 4}})
            assert toned == {"tone": {**site.app.launcher.tone_for("debate"), "humor": 4},
                             "mode": "debate"}
            assert site.app.launcher.tones["debate"]["humor"] == 4
            pushed = post("/api/hud/menu", {"action": "tone", "mode": "debate",
                                            "tone": {"humor": 1, "attack": 3}})
            assert pushed["tone"]["humor"] == 1
            assert session._tone.as_payload()["humor"] == 1
            assert session._tone.as_payload()["attack"] == 3
            # The push only reaches sessions of that mode.
            assert site.app.copilot.apply_tone({"directness": 4}, "litigation") == 0
            assert site.app.copilot.apply_tone({"listening": 0}, "debate") == 1
            posted = post("/api/copilot/turn", {"session_id": session_id,
                                                "speaker": "Opponent", "text": "Cars are best."})
            assert posted["frame"]["status"] == "thinking"
            assert session.wait_idle(3)
            with urllib.request.urlopen(
                site.url + "/api/copilot/events?session_id=" + session_id, timeout=3
            ) as response:
                chunk = b""
                while b"\n\n" not in chunk:
                    chunk += response.read1(4096)
            payload = json.loads(chunk.split(b"data: ", 1)[1].split(b"\n\n", 1)[0])
            assert payload["cue"]["kind"] == "question" and payload["turn_id"] == 1
            assert payload["prompt"].startswith("Suggested:")
            context = json.loads(calls[0]["messages"][1]["content"])
            assert context["session"]["goal"] == "Discuss transport"
            assert context["recent_turns"][-1]["text"] == "Cars are best."
            output = io.StringIO()
            JsonLinesTransport(output).send(session.frames_after()[-1])
            assert json.loads(output.getvalue()) == payload
            emulator = TerminalGlassesEmulator(out=io.StringIO())
            emulator.feed(payload)
            next_frame = session.feed_transcript(TranscriptLine("Opponent", "A revised claim"))
            emulator.feed(frame_to_payload(next_frame))
            assert len(emulator._frames) == 1 and emulator._frames[0]["prompt"] is None
            post("/api/copilot/stop", {"session_id": session_id})
            assert session.closed
            with pytest.raises(urllib.error.HTTPError) as exc:
                post("/api/copilot/turn", {"session_id": session_id, "text": "late"})
            assert exc.value.code == 404
        finally:
            site.server.shutdown()
            site.server.server_close()
            thread.join(2)
