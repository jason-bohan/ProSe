from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from prose.copilot import CopilotError, ModelSettings
from prose.debate import (
    COACH_PROMPT,
    OPPONENT_PROMPT,
    DebateConfig,
    DebateConflict,
    DebateSession,
)
from prose.web import build_site


class FakeModel:
    settings = ModelSettings("http://localhost:1234/v1", "test")

    def __init__(self):
        self.calls = []
        self.fail_coach = False

    def complete_json(self, prompt, context, **kwargs):
        self.calls.append((prompt, context))
        if prompt == OPPONENT_PROMPT:
            return {"reply": "How would you cover the cost?"}
        if self.fail_coach:
            raise CopilotError("Provider unavailable")
        return {"suggestion": "Let's compare the costs of both choices.",
                "why": "Examine the actual tradeoff.", "feedback": "", "check": ""}


def practice():
    model = FakeModel()
    session = DebateSession(DebateConfig("Public transit", "Invest in reliable service"), model)
    session.start()
    return session, model


def test_coach_opening_then_separate_opponent_and_coach():
    session, model = practice()
    opening = session.snapshot()
    assert opening["turn"] == 0 and opening["messages"] == []
    assert opening["coach"]["suggestion"]
    result = session.reply("Transit expands access to jobs.", 0)
    assert result["turn"] == 1
    assert [m["speaker"] for m in result["messages"]] == ["You", "AI opponent"]
    assert [call[0] for call in model.calls] == [COACH_PROMPT, OPPONENT_PROMPT, COACH_PROMPT]
    assert len(model.calls[1][1]["conversation"]) == 1
    assert len(model.calls[2][1]["conversation"]) == 2
    assert model.calls[2][1]["last_user_reply"] == "Transit expands access to jobs."
    assert model.calls[2][1]["last_opponent_reply"] == "How would you cover the cost?"
    assert model.calls[1][1]["brief"]["temperament"] == "stubborn"
    assert model.calls[1][1]["brief"]["persona"] == "maga"


def test_failed_coach_leaves_turn_retryable_without_duplicate():
    session, model = practice()
    model.fail_coach = True
    with pytest.raises(CopilotError):
        session.reply("My argument", 0)
    assert session.snapshot()["turn"] == 0
    model.fail_coach = False
    assert session.reply("My argument", 0)["turn"] == 1
    with pytest.raises(DebateConflict):
        session.reply("Duplicate", 0)
    assert session.snapshot()["turn"] == 1


def test_switch_model_preserves_conversation_and_retries_failed_turn():
    session, first = practice()
    session.reply("First point", 0)
    first.fail_coach = True
    with pytest.raises(CopilotError):
        session.reply("My next point", 1)
    before = session.snapshot()
    second = FakeModel()
    second.settings = ModelSettings("http://localhost:11434/v1", "qwen3-coder:30b")
    changed = session.change_model("mac-studio", second, 1)
    assert changed["messages"] == before["messages"]
    assert changed["coach"] == before["coach"]
    assert changed["coach_model"] == first.settings.model
    assert changed["model_id"] == "mac-studio"
    after = session.reply("My next point", 1)
    assert after["turn"] == 2 and after["coach_model"] == "qwen3-coder:30b"
    assert len(second.calls[0][1]["conversation"]) == 3
    assert len(after["messages"]) == 4
    with pytest.raises(DebateConflict):
        session.change_model("configured", first, 1)
    with pytest.raises(ValueError):
        session.change_model("configured", first, True)


@pytest.mark.parametrize("data", [
    {"topic": "", "position": "a"},
    {"topic": "a", "position": []},
    {"topic": "a", "position": "b", "persona": "unknown"},
    {"topic": "a", "position": "b", "temperament": "unknown"},
    {"topic": "a", "position": "b", "persona": "custom"},
])
def test_invalid_briefs(data):
    with pytest.raises(ValueError):
        DebateConfig.from_dict(data)


def test_custom_persona_and_explicit_opponent_position():
    config = DebateConfig.from_dict({"topic": "Budget", "position": "Fund parks",
                                    "persona": "custom", "custom_persona": "City accountant",
                                    "opponent_position": "Prioritize roads"})
    assert config.brief()["custom_persona"] == "City accountant"
    assert config.brief()["opponent_position"] == "Prioritize roads"


def test_twenty_round_limit_and_stopping():
    session, _ = practice()
    for turn in range(20):
        result = session.reply("A point", turn)
    assert result["complete"] and len(result["messages"]) == 40
    with pytest.raises(DebateConflict):
        session.reply("More", 20)
    session.close()
    with pytest.raises(KeyError):
        session.snapshot()


def test_concurrent_turn_and_stop_discard_inflight_reply():
    session, model = practice()
    entered, release = threading.Event(), threading.Event()
    respond = model.complete_json

    def blocked(prompt, context, **kwargs):
        entered.set()
        assert release.wait(3)
        return respond(prompt, context, **kwargs)

    model.complete_json = blocked
    failures = []

    def send():
        try:
            session.reply("First", 0)
        except KeyError:
            failures.append("stopped")

    worker = threading.Thread(target=send)
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.raises(DebateConflict):
            session.reply("Second", 0)
        with pytest.raises(DebateConflict):
            session.snapshot()
        with pytest.raises(DebateConflict):
            session.change_model("other", FakeModel(), 0)
        session.close()
    finally:
        release.set()
        worker.join(3)
    assert failures == ["stopped"]
    assert session._turns == []


def test_practice_http_routes(monkeypatch):
    monkeypatch.setattr("prose.debate.ModelCoach", lambda settings, **kwargs: FakeModel())
    monkeypatch.setattr(ModelSettings, "from_env", lambda **kwargs: FakeModel.settings)
    site = build_site("127.0.0.1", 0)
    server = threading.Thread(target=site.server.serve_forever, daemon=True)
    server.start()

    def post(path, data, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        request = urllib.request.Request(site.url + "/api/practice/" + path,
                                         data=json.dumps(data).encode(), headers=headers)
        with urllib.request.urlopen(request, timeout=4) as response:
            return json.load(response)

    try:
        with urllib.request.urlopen(site.url + "/practice") as response:
            page = response.read().decode()
        assert "MAGA supporter" in page and 'id="use-suggestion"' in page
        assert 'id="practice-model"' in page and "ChatJimmy" in page
        state = post("sessions", {"topic": "Transit", "position": "Expand service"})
        sid = state["session_id"]
        assert state["turn"] == 0
        turn = {"session_id": sid, "text": "My point", "expected_turn": 0}
        assert post("turn", turn)["turn"] == 1
        with pytest.raises(urllib.error.HTTPError) as stale:
            post("turn", turn)
        assert stale.value.code == 409
        with pytest.raises(urllib.error.HTTPError) as cross_origin:
            post("turn", turn, "https://example.com")
        assert cross_origin.value.code == 403
        assert post("state", {"session_id": sid})["turn"] == 1
        switched = post("model", {"session_id": sid, "expected_turn": 1,
                                  "model_id": "chatjimmy"})
        assert switched["model_id"] == "chatjimmy" and switched["turn"] == 1
        assert len(switched["messages"]) == 2
        with pytest.raises(urllib.error.HTTPError) as bad_model:
            post("model", {"session_id": sid, "expected_turn": 1,
                           "model_id": "http://attacker.example"})
        assert bad_model.value.code == 400
        assert post("stop", {"session_id": sid})["stopped"]
        with pytest.raises(urllib.error.HTTPError) as stopped:
            post("state", {"session_id": sid})
        assert stopped.value.code == 404
    finally:
        site.server.shutdown()
        site.server.server_close()
        server.join(3)
