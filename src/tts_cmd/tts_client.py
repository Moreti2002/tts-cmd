"""Provider-agnostic TTS client interface and factory.

The service only depends on this module; each provider lives in its own
module (``openai_tts``, ``gemini_tts``) and is imported lazily so only the
SDK of the active provider needs to be importable at runtime.
"""

from __future__ import annotations

from typing import Protocol

from .config import Settings


class TTSClient(Protocol):
    def synthesize_wav(self, text: str) -> bytes:
        """Return a complete WAV file (with header) speaking ``text``."""
        ...


def create_client(settings: Settings) -> TTSClient:
    if settings.provider == "gemini":
        from .gemini_tts import GeminiTTSClient

        return GeminiTTSClient(settings)
    if settings.provider == "openai":
        from .openai_tts import OpenAITTSClient

        return OpenAITTSClient(settings)
    raise ValueError(f"unknown TTS provider: {settings.provider!r}")
