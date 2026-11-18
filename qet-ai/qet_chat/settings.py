"""Remembered settings (JSON in %APPDATA%\\QetChat) and API keys (Windows
Credential Manager via keyring, never written to disk in plain text)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import keyring

SETTINGS_DIR = Path(os.environ.get("APPDATA", Path.home())) / "QetChat"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
KEYRING_SERVICE = "qet-chat"

# name -> (kind, default base URL, default model, needs key)
PROVIDERS: dict[str, tuple[str, str, str, bool]] = {
    "Claude":               ("anthropic", "", "claude-sonnet-5-5", True),
    "LM Studio (local)":    ("openai", "http://127.0.0.1:1234/v1", "", False),
    "Ollama (local)":       ("openai", "http://127.0.0.1:11434/v1", "", False),
    "DeepSeek":             ("openai", "https://api.deepseek.com", "deepseek-chat", True),
    "Other (OpenAI-style)": ("openai", "", "", True),
}


@dataclass
class Settings:
    provider: str = "Claude"
    models: dict[str, str] = field(default_factory=dict)      # per provider
    base_urls: dict[str, str] = field(default_factory=dict)   # per provider
    drawings_dir: str = r"F:\QelectricoTech\drawings"
    current_drawing: str = ""

    def model(self, provider: str | None = None) -> str:
        p = provider or self.provider
        return self.models.get(p) or PROVIDERS.get(p, ("", "", "", False))[2]

    def base_url(self, provider: str | None = None) -> str:
        p = provider or self.provider
        return self.base_urls.get(p) or PROVIDERS.get(p, ("", "", "", False))[1]

    def kind(self, provider: str | None = None) -> str:
        return PROVIDERS.get(provider or self.provider, ("openai",))[0]

    def needs_key(self, provider: str | None = None) -> bool:
        return PROVIDERS.get(provider or self.provider, ("", "", "", True))[3]

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
            s = cls(**known)
        except (OSError, ValueError, TypeError):
            s = cls()
        if s.provider not in PROVIDERS:
            s.provider = "Claude"
        return s

    def save(self) -> None:
        SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)


def get_api_key(provider: str) -> str:
    try:
        return keyring.get_password(KEYRING_SERVICE, provider) or ""
    except Exception:  # noqa: BLE001 - a broken keyring must not stop the app
        return ""


def set_api_key(provider: str, key: str) -> None:
    if key:
        keyring.set_password(KEYRING_SERVICE, provider, key)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, provider)
        except Exception:  # noqa: BLE001
            pass
