"""Experimental adapter for ChatJimmy's public demo chat interface."""

from __future__ import annotations

import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .copilot import CopilotError, ModelSettings, _NoRedirect

ENDPOINT = "https://chatjimmy.ai/api/chat"
MODEL = "llama3.1-8B"
INPUT_LIMIT = 18000


class ChatJimmyFormatError(CopilotError):
    """A completed response with invalid JSON; eligible for one format retry."""


def prepare_messages(system_prompt: str, context: dict) -> list[dict]:
    context = dict(context)
    history_key = "conversation" if "conversation" in context else "recent_turns"
    history = list(context.get(history_key, []))
    omitted = 0
    suffix = ("\n\nReturn one valid JSON object only. Double-quote every property name and "
              "string. No introduction, Markdown, or commentary outside the JSON. "
              "Do not infer facts from omitted conversation turns.")
    if "practice" in context:
        suffix += (" Use only supplied target words for vocabulary feedback. "
                   "The persona describes the opponent, not the user. "
                   "Your suggestion must help argue user.position while answering the opponent; "
                   "do not just repeat the opponent's position. "
                   "Only assess wording actually present in the user's latest reply.")
        if context["practice"].get("method") == "listening":
            suffix += (" The exercise is active listening: restate the opponent's strongest "
                       "point, confirm understanding, then address it. Use this for method_tip.")
        if not history:
            suffix += (" This is the opening: nobody has spoken yet; feedback and "
                       "listening must be empty.")
        suffix += " Vocabulary feedback is limited to these words: " + json.dumps(
            [item["word"] for item in context.get("target_words", [])]
        ) + ". Actual matches in the user's reply: " + json.dumps(
            context.get("user_used_target_words", [])
        ) + "."
    while True:
        if history_key in context:
            context[history_key] = history
        if omitted:
            context["earlier_turns_omitted"] = omitted
        messages = [{"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False) + suffix}]
        if len(json.dumps(messages, ensure_ascii=False).encode("utf-8")) <= INPUT_LIMIT:
            return messages
        if len(history) <= 2:
            raise CopilotError("This brief is too long for the ChatJimmy demo. "
                               "Shorten your notes or reply, or use another model.")
        history.pop(0)
        omitted += 1


def parse_response(raw: bytes) -> dict:
    try:
        text = raw.decode("utf-8")
        body, marker, footer = text.rpartition("<|stats|>")
        if not marker or not footer.rstrip().endswith("<|/stats|>"):
            raise ValueError("missing completion status")
        stats = json.loads(footer.rstrip().removesuffix("<|/stats|>"))
        if stats.get("done") is not True or stats.get("done_reason") != "stop":
            raise ValueError("incomplete response")
        if stats.get("status", 0) != 0:
            raise ValueError("provider failure")
    except (UnicodeError, ValueError, TypeError, AttributeError) as exc:
        raise CopilotError("ChatJimmy did not finish its reply. Your draft is still available; "
                           "retry or choose a different AI model above.") from exc
    try:
        # Accept harmless prose/fences around one complete JSON object. Never repair
        # missing quotes/braces or promote truncated text into an accepted answer.
        body = body.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*\n(.*?)\s*```", body, re.S | re.I)
        if fenced:
            body = fenced.group(1).strip()
        start = body.find("{")
        if start < 0 or "[" in body[:start]:
            raise ValueError("missing object")
        result, end = json.JSONDecoder().raw_decode(body, start)
        if "{" in body[end:] or "}" in body[end:]:
            raise ValueError("ambiguous extra object")
        if not isinstance(result, dict):
            raise ValueError("expected an object")
        return result
    except (ValueError, TypeError) as exc:
        raise ChatJimmyFormatError(
            "ChatJimmy could not format its reply. Your draft is still available; "
            "retry or choose a different AI model above.") from exc


def complete_json(settings: ModelSettings, system_prompt: str, context: dict) -> dict:
    if settings.model != MODEL:
        raise CopilotError(f"The ChatJimmy demo currently exposes {MODEL}.")
    messages = prepare_messages(system_prompt, context)
    deadline = time.monotonic() + settings.timeout
    for attempt in range(2):
        if attempt:
            # Retry only complete but malformed output, within the original time budget.
            # No retry on quota, HTTP, timeout, or incomplete generation errors.
            fields = re.findall(r'"([a-z_]+)"\s*:', system_prompt)
            schema = json.dumps(dict.fromkeys(fields, "short text"))
            retry_prompt = system_prompt + (
                "\nYour previous response was not valid JSON. Use double-quoted keys and values. "
                "Keep every value to one short sentence. Output exactly this object structure "
                "with your actual answer replacing each placeholder: " + schema
            )
            messages = prepare_messages(retry_prompt, context)
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise CopilotError("ChatJimmy ran out of time. Your draft is still available; "
                               "choose another AI model or retry.")
        payload = {"messages": messages, "chatOptions": {"selectedModel": MODEL, "topK": 1}}
        try:
            return parse_response(_request(payload, remaining))
        except ChatJimmyFormatError:
            if attempt:
                raise
    raise AssertionError("unreachable")


def _request(payload: dict, timeout: float) -> bytes:
    # The demo has no user API-key field. Never forward another provider's key.
    request = Request(ENDPOINT, data=json.dumps(payload).encode("utf-8"), headers={
        "Content-Type": "application/json", "Accept": "text/event-stream",
        "User-Agent": "ProSe-ChatJimmy/1.0",
    }, method="POST")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(256001)
        if len(raw) > 256000:
            raise CopilotError("ChatJimmy response exceeded the size limit.")
        return raw
    except HTTPError as exc:
        raise CopilotError(f"ChatJimmy demo returned HTTP {exc.code}. "
                           "Try later or choose another provider.") from None
    except (URLError, OSError, TimeoutError) as exc:
        raise CopilotError("ChatJimmy demo is unavailable or timed out. "
                           "Your draft is still available.") from exc
