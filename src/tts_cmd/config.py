"""Configuration loading and runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = PROJECT_ROOT / "assets"
ACTIVATION_SOUND_PATH = ASSETS_DIR / "activation.wav"
DEACTIVATION_SOUND_PATH = ASSETS_DIR / "deactivation.wav"

# ``.api-keys`` is where ~/linux-config keeps secrets (export KEY=... lines,
# which python-dotenv parses fine); the ``.env`` paths remain as overrides.
_ENV_PATHS = [
    Path.home() / "linux-config" / ".api-keys",
    Path.home() / "linux-config" / ".env",
    PROJECT_ROOT / ".env",
]

# Per-provider defaults. Select with TTS_PROVIDER; model/voice defaults only
# apply when TTS_MODEL / TTS_VOICE are not set.
_PROVIDERS = {
    "gemini": {
        "key_env": "GEMINI_API_KEY",
        "model": "gemini-3.1-flash-tts-preview",
        "voice": "Kore",
    },
    "openai": {
        "key_env": "OPENAI_API_KEY",
        "model": "gpt-4o-mini-tts",
        "voice": "coral",
    },
}

DEFAULT_PROVIDER = "gemini"


@dataclass(frozen=True)
class Settings:
    provider: str
    api_key: str
    model: str
    voice: str
    response_format: str = "pcm"
    sample_rate: int = 24_000
    speed: float = 1.4  # OpenAI only; Gemini paces via ``instructions``.
    instructions: str = (
        "Speak in a clear, natural, and engaging tone at a brisk pace. "
        "Mirror the language of the input text. "
        "The word 'Claude' is the name of the Claude AI assistant: pronounce "
        "it as a name ('clohd', rhyming with 'flawed'), never as the English "
        "word 'cloud', and never translate it as computing cloud."
    )
    daemon_host: str = "127.0.0.1"
    daemon_port: int = 47284


def _load_env() -> None:
    for path in _ENV_PATHS:
        if path.is_file():
            load_dotenv(path, override=False)


def load_settings() -> Settings:
    _load_env()

    provider = os.environ.get("TTS_PROVIDER", DEFAULT_PROVIDER).lower()
    if provider not in _PROVIDERS:
        raise RuntimeError(
            f"Unknown TTS_PROVIDER {provider!r}; expected one of {sorted(_PROVIDERS)}."
        )

    defaults = _PROVIDERS[provider]
    api_key = os.environ.get(defaults["key_env"])
    if not api_key:
        raise RuntimeError(
            f"{defaults['key_env']} not set. Expected in "
            f"{_ENV_PATHS[0]} or environment."
        )

    return Settings(
        provider=provider,
        api_key=api_key,
        model=os.environ.get("TTS_MODEL", defaults["model"]),
        voice=os.environ.get("TTS_VOICE", defaults["voice"]),
        speed=float(os.environ.get("TTS_SPEED", "1.4")),
        daemon_host=os.environ.get("TTS_HOST", "127.0.0.1"),
        daemon_port=int(os.environ.get("TTS_PORT", "47284")),
    )
