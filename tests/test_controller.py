from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

import pytest

from prose.copilot import ModelSettings
from prose.debate import OPPONENT_PROMPT
from prose.hudhub import HudHub
from prose.launcher import Launcher, SessionScore, practice_frame
from prose.web import WebSite, build_site


class FakeModel:
    settings = ModelSettings("http://localhost:1234/v1", "test")

    def complete_json(self, prompt, context, **kwargs):
        if prompt == OPPONENT_PROMPT:
            return {"reply": "How would you cover the cost?"}
        return {
            "suggestion": "Compare the actual tradeoff with the record.",
            "why": "Ground the claim in evidence.",
            "feedback": "",
            "check": "",
        }


def _site() -> WebSite:
    site = build_site("127.0.0.1", 0)
    threading.Thread(target=site.server.serve_forever, daemon=True).start()
    return site


def _post(site: WebSite, path: str, data: dict, origin: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if origin:
        headers["Origin"] = origin
    request = urllib.request.Request(
        site.url + path, data=json.dumps(data).encode(), headers=headers
    )
    with urllib.request.urlopen(request, timeout=4) as response:
        return json.load(response)


def test_launcher_menu_move_select_back() -> None:
    launcher = Launcher()
    snapshot = launcher.snapshot()
    assert snapshot["index"] == 0 and snapshot["state"] == "menu"
    assert [m["id"] for m in snapshot["modes"]] == ["debate", "litigation", "tone"]
    assert snapshot["tone_mode"] == "debate"
    assert snapshot["tone"] == {"humor": 2, "rhetoric": 2, "attack": 2, "listening": 2}
    launcher.move(1)
    assert launcher.snapshot()["index"] == 1
    launcher.move(1)
    assert launcher.snapshot()["index"] == 2
    launcher.move(1)
    assert launcher.snapshot()["index"] == 0
    launcher.move(-1)
    assert launcher.snapshot()["index"] == 2
    launcher.select()
    assert launcher.state == "tone"  # picking the matrix entry opens it
    launcher.back()
    launcher.move(-1)  # back onto litigation at index 1
    assert launcher.snapshot()["index"] == 1
    mode = launcher.select()
    assert mode["id"] == "litigation" and launcher.state == "setup"
    assert launcher.tone_mode == "litigation"  # setup primes the matrix
    payload = launcher.payload()
    assert payload["version"] == 2 and payload["status"] == "ready"
    assert len(payload["prompt"]) <= 140 and "configure" in payload["prompt"]
    assert payload["hud"]["state"] == "setup"
    launcher.move(1)
    assert launcher.state == "menu" and launcher.mode == ""
    menu = launcher.payload()
    assert menu["speaker"] == "TONE 3/3"
    assert menu["prompt"].startswith("> Personality matrix")
    launcher.select()
    launcher.back()
    assert launcher.state == "menu" and launcher.mode == ""


def test_launcher_personality_matrix_bipolar_axes() -> None:
    launcher = Launcher()
    launcher.select()  # debate setup primes the debate matrix
    launcher.back()
    launcher.move(1)
    launcher.move(1)  # cursor on the matrix entry
    entry = launcher.select()
    assert entry["id"] == "tone" and launcher.state == "tone"
    snapshot = launcher.snapshot()
    assert snapshot["tone_mode"] == "debate"
    assert snapshot["tone_poles"]["debate"]["humor"] == ["humor", "seriousness"]
    assert snapshot["tone_poles"]["litigation"]["urgency"] == ["unhurried", "urgent"]
    payload = launcher.payload()
    assert payload["speaker"] == "TONE debate"
    assert payload["prompt"] == "humor [##--] seriousness 2/4"
    launcher.move(1)
    assert launcher.snapshot()["tone"]["humor"] == 3
    for _ in range(6):
        launcher.move(1)
    assert launcher.snapshot()["tone"]["humor"] == 4  # clamped at the high pole
    launcher.dial_step(1)
    assert launcher.payload()["prompt"].startswith("reason [##--] rhetoric")
    launcher.select()  # cycles to the attack trait
    assert launcher.snapshot()["dial"] == 2
    launcher.set_mode("litigation")
    snapshot = launcher.snapshot()
    assert snapshot["tone_mode"] == "litigation" and snapshot["dial"] == 2
    assert snapshot["tone"] == {"directness": 2, "formality": 2,
                                "encouragement": 2, "urgency": 2}
    with pytest.raises(ValueError):
        launcher.set_mode("nonsense")
    with pytest.raises(ValueError):
        launcher.set_tone({"humor": 2}, "litigation")  # debate trait on the wrong matrix
    launcher.back()
    assert launcher.state == "menu"


def test_glasses_buttons_drive_the_launcher() -> None:
    launcher = Launcher()
    launcher.press("down")
    assert launcher.snapshot()["index"] == 1
    launcher.press("select")
    assert launcher.state == "setup" and launcher.tone_mode == "litigation"
    launcher.press("down")  # nav is inert in setup, like on the phone controller
    launcher.press("select")
    assert launcher.state == "setup"
    launcher.press("back")
    assert launcher.state == "menu"
    launcher.press("up")
    assert launcher.snapshot()["index"] == 0
    launcher.press("home")
    assert launcher.snapshot()["index"] == 0
    launcher.move(1)
    launcher.move(1)  # onto the matrix entry
    launcher.press("select")
    assert launcher.state == "tone" and launcher.tone_mode == "litigation"
    launcher.press("up")  # raise the highlighted trait toward its high pole
    assert launcher.snapshot()["tone"]["directness"] == 3
    launcher.press("right")  # next trait
    assert launcher.snapshot()["dial"] == 1
    launcher.press("scroll_up")  # flip to the debate matrix
    assert launcher.snapshot()["tone_mode"] == "debate" and launcher.snapshot()["dial"] == 1
    launcher.press("back")
    assert launcher.state == "menu"
    with pytest.raises(ValueError):
        launcher.press("nope")


def test_session_score_hit_blowout_and_mood() -> None:
    score = SessionScore()
    score.turn({"messages": [], "words_used": []})
    assert score.momentum == 50 and not score.hit
    assert score.mood() == ("neutral", 2)
    hit = score.turn(
        {
            "messages": [
                {"speaker": "You", "text": "Reliable service expands job access."},
                {"speaker": "AI opponent", "text": "At what cost?"},
            ],
            "words_used": ["prudent"],
        }
    )
    assert hit["hit"] and hit["delta"] >= 8
    assert score.momentum == 58
    assert score.mood() == ("frustrated", 5)
    blown = score.turn(
        {
            "messages": [
                {"speaker": "You", "text": "Short point."},
                {"speaker": "AI opponent", "text": "x" * 400},
            ],
            "words_used": ["prudent"],
        }
    )
    assert not blown["hit"] and blown["delta"] == -SessionScore.BLOWOUT_PENALTY
    losing = SessionScore(momentum=30)
    losing.turn(
        {
            "messages": [
                {"speaker": "You", "text": "Same size argument here."},
                {"speaker": "AI opponent", "text": "Same size argument here."},
            ],
            "words_used": [],
        }
    )
    assert losing.mood() == ("confident", 3)
    winning = SessionScore(momentum=70)
    winning.turn(
        {
            "messages": [
                {"speaker": "You", "text": "Same size argument here."},
                {"speaker": "AI opponent", "text": "Same size argument here."},
            ],
            "words_used": [],
        }
    )
    assert winning.mood() == ("tense", 3)
    floored = SessionScore(momentum=8)
    floored.turn(
        {
            "messages": [
                {"speaker": "You", "text": "One."},
                {"speaker": "AI opponent", "text": "y" * 400},
            ],
            "words_used": [],
        }
    )
    assert floored.momentum == SessionScore.MIN_MOMENTUM


def test_practice_frame_shapes() -> None:
    score = SessionScore()
    start_state = {
        "turn": 0,
        "config": {"topic": "Transit"},
        "coach": {"suggestion": "Open with the record."},
        "messages": [],
    }
    start = practice_frame(
        start_state, score, "start", {"hit": False, "delta": 0, "momentum": 50}
    )
    assert start["speaker"] == "READY" and start["status"] == "ready"
    assert start["version"] == 2
    assert start["prompt"].startswith("Open with")
    assert start["momentum_pct"] == 50
    turn_state = {
        "turn": 3,
        "config": {"topic": "Transit"},
        "coach": {"suggestion": "Answer the cost point with the study."},
        "messages": [
            {"speaker": "You", "text": "Farebox recovery lags only in off-peak."},
            {"speaker": "AI opponent", "text": "Then who pays?"},
        ],
        "words_used": ["prudent"],
    }
    score.turn(turn_state)
    turn = practice_frame(turn_state, score, "turn", {"hit": True, "delta": 8, "momentum": 58})
    assert turn["speaker"] == "R3 OPPONENT"
    assert turn["mood_label"] == "frustrated" and turn["mood_intensity"] == 5
    assert turn["momentum_pct"] == score.momentum
    assert turn["hud"]["hit"] is True


def test_hub_replay_and_fanout() -> None:
    hub = HudHub()
    hub.publish({"version": 2, "prompt": "first"})
    subscriber = hub.subscribe()
    assert subscriber.get_nowait()["seq"] == 1
    second = hub.publish({"prompt": "second"})
    assert second["seq"] == 2
    assert subscriber.get_nowait()["prompt"] == "second"
    assert hub.current is not None and hub.current["prompt"] == "second"
    hub.unsubscribe(subscriber)
    hub.publish({"prompt": "third"})
    assert subscriber.empty()


def test_controller_page_and_menu_routes() -> None:
    site = _site()
    try:
        with urllib.request.urlopen(site.url + "/controller", timeout=4) as response:
            page = response.read().decode()
        assert 'id="view-menu"' in page and 'id="gamepad"' in page
        assert "width=device-width" in page and "NOT LEGAL ADVICE" in page
        assert "START" in page and "CONFIDENCE" in page
        with urllib.request.urlopen(site.url + "/api/hud/menu", timeout=4) as response:
            snap = json.load(response)
        assert snap["index"] == 0 and len(snap["modes"]) == 3
        assert snap["tone_poles"]["debate"]["attack"] == ["build", "attack"]
        current = site.app.hub.current
        assert current is not None and current["prompt"].startswith("> Debate practice")
        moved = _post(site, "/api/hud/menu", {"action": "move", "delta": 1})
        assert moved["index"] == 1
        current = site.app.hub.current
        assert current is not None and current["prompt"].startswith("> Litigation practice")
        picked = _post(site, "/api/hud/menu", {"action": "select"})
        assert picked["state"] == "setup" and picked["mode"] == "litigation"
        current = site.app.hub.current
        assert current is not None and "configure" in current["prompt"]
        with pytest.raises(urllib.error.HTTPError) as cross_origin:
            _post(site, "/api/hud/menu", {"action": "select"}, "https://example.com")
        assert cross_origin.value.code == 403
        backed = _post(site, "/api/hud/menu", {"action": "back"})
        assert backed["state"] == "menu"
        # The phone relay posts glasses accessory buttons cross-origin; menu
        # navigation stays same-origin (tone/mode are the only menu writes a
        # foreign origin may perform, for the relay's matrix pads below).
        pressed = _post(site, "/api/hud/button", {"button": "down"},
                        "https://example.com")
        assert pressed["index"] == 2  # wrapped from litigation onto the matrix
        chosen = _post(site, "/api/hud/menu", {"action": "select"})
        assert chosen["state"] == "tone" and chosen["tone_mode"] == "litigation"
        edited = _post(site, "/api/hud/menu",
                       {"action": "tone", "mode": "litigation",
                        "tone": {"directness": 4, "urgency": 1}})
        assert edited["tone"]["directness"] == 4 and edited["tone"]["urgency"] == 1
        assert edited["state"] == "tone"
        flipped = _post(site, "/api/hud/menu", {"action": "mode", "mode": "debate"})
        assert flipped["tone_mode"] == "debate"
        # The relay app's embedded matrix pads write tone/mode cross-origin;
        # navigation actions above stay blocked on other origins.
        padded = _post(site, "/api/hud/menu",
                       {"action": "tone", "mode": "debate",
                        "tone": {"humor": 3, "rhetoric": 1, "attack": 2,
                                 "listening": 4}},
                       "https://example.com")
        assert padded["tone"]["humor"] == 3 and padded["tone_mode"] == "debate"
        seg = _post(site, "/api/hud/menu", {"action": "mode", "mode": "litigation"},
                    "https://example.com")
        assert seg["tone_mode"] == "litigation"
    finally:
        site.server.shutdown()


def test_hud_menu_preflight_for_relay() -> None:
    site = _site()
    try:
        host, port = site.server.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=4)
        try:
            connection.request(
                "OPTIONS", "/api/hud/menu",
                headers={"Origin": "https://example.com",
                         "Access-Control-Request-Method": "POST"})
            response = connection.getresponse()
            response.read()
            assert response.status == 204
            assert response.getheader("Access-Control-Allow-Origin") == "*"
            allow = response.getheader("Access-Control-Allow-Methods") or ""
            assert "POST" in allow and "OPTIONS" in allow
        finally:
            connection.close()
    finally:
        site.server.shutdown()


def test_practice_turn_publishes_glass_frames(monkeypatch) -> None:
    monkeypatch.setattr(
        "prose.debate.ModelCoach", lambda settings, **kwargs: FakeModel()
    )
    monkeypatch.setattr(ModelSettings, "from_env", lambda **kwargs: FakeModel.settings)
    site = _site()
    try:
        doc = urlencode({"name": "Transit study", "text": "Ridership up 12 percent."}).encode()
        doc_request = urllib.request.Request(site.url + "/documents", data=doc)
        with urllib.request.urlopen(doc_request, timeout=4) as response:
            response.read()
        created = _post(
            site,
            "/api/practice/sessions",
            {
                "topic": "Transit",
                "position": "Expand service",
                "document_ids": ["PROSE-000001"],
            },
        )
        assert created["turn"] == 0
        frame = site.app.hub.current
        assert frame is not None and frame["status"] == "ready"
        assert frame["version"] == 2 and frame["speaker"] == "READY"
        turn = _post(
            site,
            "/api/practice/turn",
            {
                "session_id": created["session_id"],
                "text": "Reliable service expands job access.",
                "expected_turn": 0,
            },
        )
        assert turn["turn"] == 1
        assert turn["hud_score"]["momentum"] == 50
        assert turn["hud_score"]["hit"] is False
        frame = site.app.hub.current
        assert frame is not None and frame["speaker"].startswith("R1")
        assert frame["momentum_pct"] == 50
        assert "transcript" in frame and frame["prompt"]
        stopped = _post(
            site, "/api/practice/stop", {"session_id": created["session_id"]}
        )
        assert stopped["stopped"] is True
        frame = site.app.hub.current
        assert frame is not None and frame["prompt"].startswith("> Debate practice")
    finally:
        site.server.shutdown()


def test_relay_app_carries_controller_and_matrix() -> None:
    root = Path(__file__).resolve().parent.parent
    source = root / "integrations" / "memomind"
    html = (source / "index.html").read_text(encoding="utf-8")
    js = (source / "plugin.mjs").read_text(encoding="utf-8")
    assert 'id="controller"' in html and 'id="matrix"' in html
    assert ".xy-grid" in html and 'id="tone-debate"' in html
    for marker in ("bindMatrixPad", "syncControllerHref", "onMessage",
                   "/api/hud/button", "/api/hud/menu"):
        assert marker in js
    # Browser Studio serves the PhoneSDK copy; drift breaks the phone app.
    example = (root / ".tools" / "memomind-sdk" / "PhoneSDK" / "examples"
               / "prose-live-coach")
    if example.is_dir():
        for name in ("index.html", "plugin.mjs"):
            assert (source / name).read_bytes() == (example / name).read_bytes(), name
