"""Server-owned model choices; browsers can select IDs, never supply endpoints or keys."""

from __future__ import annotations

import ipaddress
import json
import math
import re
from pathlib import Path
from urllib.parse import urlparse

from .copilot import CopilotError, ModelSettings
from .lexicon import data_directory

CHATJIMMY = ModelSettings("https://chatjimmy.ai/api", "llama3.1-8B", timeout=30)


def ollama_settings(data: dict) -> ModelSettings:
    """Allow HTTP only for explicitly configured local/private inference servers."""
    base = data.get("base_url", "")
    model = data.get("model", "")
    if not isinstance(base, str) or not isinstance(model, str) or not model.strip():
        raise ValueError("Ollama profiles need base_url and model strings.")
    base = base.strip().rstrip("/")
    parsed = urlparse(base)
    try:
        address = ipaddress.ip_address(parsed.hostname or "")
        private = address.is_private or address in ipaddress.ip_network("100.64.0.0/10")
        if address.is_unspecified or address.is_multicast or address.is_link_local:
            private = False
    except ValueError:
        private = parsed.hostname == "localhost"
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/v1")
            or (parsed.scheme == "http" and not private)):
        raise ValueError("Ollama must use HTTPS or an explicit local/private HTTP address.")
    # Validate the port, including malformed/out-of-range values, before any request.
    _ = parsed.port
    if not parsed.path:
        base += "/v1"
    timeout = data.get("timeout_seconds", 60)
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or not 1 <= timeout <= 60):
        raise ValueError("Ollama timeout_seconds must be between 1 and 60.")
    if len(model) > 200 or any(ord(c) < 32 for c in model):
        raise ValueError("Invalid Ollama model name.")
    return ModelSettings(base, model.strip(), timeout=timeout,
                         transport=data.get("provider", "ollama"))


class ModelChoices:
    def __init__(self, directory: Path | None = None) -> None:
        self._settings = {"chatjimmy": CHATJIMMY}
        self._labels = {"chatjimmy": "ChatJimmy · Llama 3.1 8B"}
        self.default = "chatjimmy"
        self.error = ""
        self.specialist_id: str | None = None
        try:
            configured = ModelSettings.from_env(default_timeout=30)
            if configured.base_url != CHATJIMMY.base_url:
                self._settings["configured"] = configured
                self._labels["configured"] = "Server model · " + configured.model
                self.default = "configured"
        except CopilotError:
            pass
        path = (directory or data_directory()) / "ai-models.json"
        try:
            if not path.exists():
                return
            if path.stat().st_size > 32000:
                raise ValueError("Model configuration is too large.")
            config = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(config, dict) or config.get("version") != 1:
                raise ValueError("Expected model configuration version 1.")
            profiles = config.get("profiles", [])
            if not isinstance(profiles, list) or len(profiles) > 12:
                raise ValueError("Expected at most 12 model profiles.")
            settings, labels = dict(self._settings), dict(self._labels)
            for profile in profiles:
                if not isinstance(profile, dict):
                    raise ValueError("Each model profile must be an object.")
                key, label = profile.get("id"), profile.get("label")
                if (not isinstance(key, str) or not re.fullmatch(r"[a-z0-9-]{1,40}", key)
                        or key in settings or not isinstance(label, str)
                        or not label.strip() or len(label) > 100):
                    raise ValueError("Model profiles need unique IDs and short labels.")
                if profile.get("provider") not in ("ollama", "mlx"):
                    raise ValueError("Additional profiles support providers ollama or mlx.")
                settings[key] = ollama_settings(profile)
                labels[key] = label.strip()
            default = config.get("default", self.default)
            if not isinstance(default, str) or default not in settings:
                raise ValueError("Default model must match a configured profile ID.")
            specialist_id = config.get("legal_specialist")
            if specialist_id is not None and (
                    not isinstance(specialist_id, str) or specialist_id not in settings):
                raise ValueError("legal_specialist must match a configured profile ID.")
            self._settings, self._labels, self.default = settings, labels, default
            self.specialist_id = specialist_id
        except (OSError, ValueError, TypeError):
            self.error = "Could not load ai-models.json. Check the model setup in SETUP.md."

    def resolve(self, key: object = None) -> tuple[str, ModelSettings]:
        if key is None:
            key = self.default
        if not isinstance(key, str) or key not in self._settings:
            raise ValueError("Choose one of the listed AI models.")
        return key, self._settings[key]

    def specialist(self) -> ModelSettings:
        if self.specialist_id is None:
            raise CopilotError("Set up Saul in ai-models.json before enabling legal consultation.")
        return self._settings[self.specialist_id]

    def status(self) -> dict:
        choices = []
        for key, settings in self._settings.items():
            description = ("Experimental public demo. Replies can occasionally have format errors."
                           if key == "chatjimmy" else
                           "Runs on your local model host. Keep its server and network available."
                           if settings.transport in ("ollama", "mlx") else
                           "Uses your configured AI provider and its quota.")
            choices.append({"id": key, "label": self._labels[key], "model": settings.model,
                            "description": description})
        return {**self._settings[self.default].public_status(), "choices": choices,
                "default_model_id": self.default, "configuration_warning": self.error,
                "legal_specialist": {"configured": self.specialist_id is not None,
                                     "model_id": self.specialist_id,
                                     "model": (self.specialist().model
                                               if self.specialist_id else "")}}
