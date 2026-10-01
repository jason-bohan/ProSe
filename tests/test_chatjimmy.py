from __future__ import annotations

import io
import json

import pytest

from prose import chatjimmy
from prose.cli import main
from prose.copilot import CopilotError, ModelCoach, ModelSettings


def wire_response(body, **stats):
    status = {"done": True, "done_reason": "stop", "status": 0, **stats}
    return (body + "\n<|stats|>" + json.dumps(status) + "<|/stats|>").encode()


def test_native_response_and_fences_are_parsed():
    assert chatjimmy.parse_response(wire_response('{"reply":"A point."}')) == {"reply": "A point."}
    assert chatjimmy.parse_response(wire_response('```json\n{"reply":"A point."}\n```'))
    assert chatjimmy.parse_response(wire_response('Here is the JSON:\n{"reply":"A point."}'))
    assert chatjimmy.parse_response(wire_response('```JSON\r\n{"reply":"A point."}\r\n```'))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"reply":"no completion footer"}',
        wire_response('{"reply":"truncated"}', done_reason="length"),
        wire_response('{"reply":"failed"}', status=1),
        wire_response("Sorry, here is an unstructured answer."),
        wire_response('["wrong type"]'),
        wire_response('```json\n[{"reply":"wrong shape"}]\n```'),
        wire_response('{"reply":"first"}\n{"reply":"second"}'),
    ],
)
def test_invalid_or_incomplete_native_response_is_rejected(raw):
    with pytest.raises(CopilotError):
        chatjimmy.parse_response(raw)


def test_wrapper_uses_native_roles_and_never_forwards_credentials(monkeypatch):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            return io.BytesIO(wire_response('{"reply":"What evidence supports that?"}'))

    monkeypatch.setattr(chatjimmy, "build_opener", lambda *args: Opener())
    coach = ModelCoach(ModelSettings("https://chatjimmy.ai/api", "llama3.1-8B", "never-send"))
    assert coach.complete_json("Return JSON with reply.", {"brief": {}})["reply"]
    request = calls[0]
    assert request.full_url == chatjimmy.ENDPOINT
    assert not request.has_header("Authorization")
    assert "never-send" not in request.data.decode()
    payload = json.loads(request.data)
    assert payload["messages"][0]["role"] == "system"
    assert payload["chatOptions"]["selectedModel"] == "llama3.1-8B"


def test_context_is_bounded_without_changing_saved_history():
    history = [{"speaker": "You", "text": "Evidence. " * 300} for _ in range(16)]
    context = {"conversation": history}
    messages = chatjimmy.prepare_messages("Return JSON.", context)
    assert len(history) == len(context["conversation"]) == 16
    assert "earlier_turns_omitted" in messages[-1]["content"]
    assert len(json.dumps(messages, ensure_ascii=False).encode()) <= chatjimmy.INPUT_LIMIT
    with pytest.raises(CopilotError, match="too long"):
        chatjimmy.prepare_messages("Return JSON.", {"notes": "x" * 20000})


def test_one_retry_for_completed_malformed_json(monkeypatch):
    calls = []

    def request(payload, timeout):
        calls.append(json.loads(json.dumps(payload)))
        if len(calls) == 1:
            return wire_response('{reply:"Missing quotes on key"}')
        return wire_response('{"reply":"What evidence supports that?"}')

    monkeypatch.setattr(chatjimmy, "_request", request)
    settings = ModelSettings("https://chatjimmy.ai/api", chatjimmy.MODEL, timeout=30)
    result = chatjimmy.complete_json(settings, 'Return {"reply":"text"}', {})
    assert result["reply"] and len(calls) == 2
    assert "previous response was not valid JSON" in calls[1]["messages"][0]["content"]


def test_incomplete_generations_are_not_retried(monkeypatch):
    calls = []

    def request(payload, timeout):
        calls.append(payload)
        return wire_response('{"reply":"truncated"}', done_reason="length")

    monkeypatch.setattr(chatjimmy, "_request", request)
    with pytest.raises(CopilotError, match="did not finish"):
        chatjimmy.complete_json(ModelSettings("https://chatjimmy.ai/api", chatjimmy.MODEL),
                                'Return {"reply":"text"}', {})
    assert len(calls) == 1


@pytest.mark.parametrize("provider,ask", [("chatjimmy", False), ("groq", True)])
def test_cli_selects_provider_without_persisting_or_printing_key(
    monkeypatch, capsys, provider, ask
):
    for name in (
        "PROSE_AI_PROVIDER",
        "PROSE_AI_BASE_URL",
        "PROSE_AI_API_KEY",
        "PROSE_AI_MODEL",
        "GROQ_API_KEY",
    ):
        monkeypatch.setenv(name, "old-value")
    monkeypatch.setenv("GEMINI_API_KEY", "old-gemini-key")
    monkeypatch.setattr("getpass.getpass", lambda prompt: "new-private-key")
    settings = []
    monkeypatch.setattr(
        "prose.web.serve", lambda host, port: settings.append(ModelSettings.from_env())
    )
    args = ["serve", "--ai-provider", provider]
    if ask:
        args.append("--ask-ai-key")
    main(args)
    assert settings[0].model == (
        "llama3.1-8B" if provider == "chatjimmy" else "openai/gpt-oss-120b"
    )
    assert settings[0].api_key == ("" if provider == "chatjimmy" else "new-private-key")
    assert "new-private-key" not in capsys.readouterr().out
