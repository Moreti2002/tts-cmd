"""Configuration loading and runtime settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSETS_DIR = PROJECT_ROOT / "assets"
ACTIVATION_SOUND_PATH = ASSETS_DIR / "activation.wav"

_ENV_PATHS = [
    Path.home() / "linux-config" / ".env",
    PROJECT_ROOT / ".env",
]


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    model: str = "gpt-4o-mini-tts"
    voice: str = "coral"
    response_format: str = "pcm"
    sample_rate: int = 24_000
    instructions: str = (
        "Speak in a clear, natural, and engaging tone. "
        "Mirror the language of the input text."
    )
    daemon_host: str = "127.0.0.1"
    daemon_port: int = 47284


def _load_env() -> None:
    for path in _ENV_PATHS:
        if path.is_file():
            load_dotenv(path, override=False)


def load_settings() -> Settings:
    _load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. Expected in "
            f"{_ENV_PATHS[0]} or environment."
        )

    return Settings(
        openai_api_key=api_key,
        model=os.environ.get("TTS_MODEL", "gpt-4o-mini-tts"),
        voice=os.environ.get("TTS_VOICE", "coral"),
        daemon_host=os.environ.get("TTS_HOST", "127.0.0.1"),
        daemon_port=int(os.environ.get("TTS_PORT", "47284")),
    )
