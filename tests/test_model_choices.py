from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

from prose.copilot import CopilotError, ModelCoach, ModelSettings
from prose.model_choices import ModelChoices, ollama_settings


def profile(**changes):
    return {"id": "mac-studio", "label": "Mac Studio · Qwen3 Coder 30B",
            "provider": "ollama", "base_url": "http://100.90.227.86:11434",
            "model": "qwen3-coder:30b", **changes}


def test_saved_choices_and_default_are_loaded_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(ModelSettings, "from_env", lambda **kw: (_ for _ in ()).throw(
        CopilotError("Not configured")))
    (tmp_path / "ai-models.json").write_text(json.dumps({
        "version": 1, "default": "mac-studio", "profiles": [profile()]}), encoding="utf-8")
    choices = ModelChoices(tmp_path)
    key, settings = choices.resolve()
    assert key == "mac-studio"
    assert settings.base_url == "http://100.90.227.86:11434/v1"
    assert settings.model == "qwen3-coder:30b" and settings.transport == "ollama"
    assert settings.api_key == "" and settings.timeout == 60
    assert choices.resolve("chatjimmy")[1].model == "llama3.1-8B"
    public = choices.status()
    assert public["default_model_id"] == "mac-studio"
    assert [item["id"] for item in public["choices"]] == ["chatjimmy", "mac-studio"]
    assert "base_url" not in json.dumps(public) and "api_key" not in json.dumps(public)
    for invalid in ("http://attacker.example", "unknown", [], {}):
        with pytest.raises(ValueError):
            choices.resolve(invalid)


@pytest.mark.parametrize("url", [
    "http://public.example/v1", "http://8.8.8.8:11434", "file:///tmp/model",
    "http://user:secret@127.0.0.1:11434", "http://127.0.0.1:11434/v1?secret=x",
    "http://169.254.169.254", "http://0.0.0.0:11434", "http://127.0.0.1:99999",
    "http://127.0.0.1:11434/api/chat", "http://127.0.0.1:11434/#fragment",
])
def test_invalid_profile_endpoints_are_rejected(url):
    with pytest.raises(ValueError):
        ollama_settings(profile(base_url=url))


@pytest.mark.parametrize("url", [
    "http://localhost:11434", "http://127.0.0.1:11434/v1", "http://[::1]:11434",
    "http://192.168.1.20:11434", "https://models.example/v1",
])
def test_explicit_ollama_endpoints_are_accepted(url):
    assert ollama_settings(profile(base_url=url)).base_url.endswith("/v1")


def test_bad_config_keeps_builtin_choice_and_reports_error(tmp_path):
    (tmp_path / "ai-models.json").write_text('{"version":1,"profiles":[null]}')
    choices = ModelChoices(tmp_path)
    assert choices.status()["configuration_warning"]
    assert choices.resolve("chatjimmy")


@pytest.mark.parametrize('provider', ['ollama', 'mlx'])
def test_ollama_transport_uses_supported_token_limit_without_cloud_key(monkeypatch, provider):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {
                "content": '{"reply":"What evidence supports that?"}'}}]}).encode())

    monkeypatch.setenv("GEMINI_API_KEY", "never-send-gemini-key")
    monkeypatch.setattr("prose.copilot.build_opener", lambda *args: Opener())
    coach = ModelCoach(ollama_settings(profile(provider=provider)), max_completion_tokens=4096)
    assert coach.complete_json("Return JSON.", {})["reply"]
    payload = json.loads(calls[0].data)
    assert payload["max_tokens"] == 4096 and "max_completion_tokens" not in payload
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["stream"] is False
    assert not calls[0].has_header("Authorization")


def test_local_proxy_error_identifies_server_without_suggesting_quota(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 502, 'Bad gateway', {}, io.BytesIO(b'private'))

    monkeypatch.setattr('prose.copilot.build_opener', lambda *args: Opener())
    coach = ModelCoach(ollama_settings(profile(provider='mlx')))
    with pytest.raises(CopilotError, match='selected model server is running') as error:
        coach.complete_json('Return JSON', {})
    assert 'quota' not in str(error.value) and 'private' not in str(error.value)


@pytest.mark.parametrize('content,finish,allowed,works', [
    ('How would taxpayers cover the cost?', 'stop', True, True),
    ('How would taxpayers cover the cost?', 'stop', False, False),
    ('How would taxpayers cover the cost?', 'length', True, False),
    ('{"reply":"broken', 'stop', True, False),
    ('```json\nbroken', 'stop', True, False),
    ('<tool_call>something</tool_call>', 'stop', True, False),
    ('x' * 1801, 'stop', True, False),
])
def test_only_complete_plain_opponent_speech_can_bypass_json(
        monkeypatch, content, finish, allowed, works):
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(json.dumps({'choices': [{'finish_reason': finish,
                                 'message': {'content': content}}]}).encode())

    monkeypatch.setattr('prose.copilot.build_opener', lambda *args: Opener())
    coach = ModelCoach(ollama_settings(profile(provider='mlx')))
    if works:
        assert coach.complete_json('Opponent', {}, allow_plain_reply=allowed) == {'reply': content}
    else:
        with pytest.raises(CopilotError):
            coach.complete_json('Coach', {}, allow_plain_reply=allowed)
