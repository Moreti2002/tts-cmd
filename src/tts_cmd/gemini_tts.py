"""Gemini TTS client.

Gemini generates speech via ``generate_content`` with
``response_modalities=["AUDIO"]`` and returns raw PCM (s16le, mono) — no WAV
header. The playback backends need a complete WAV, so the PCM is wrapped
here. Style and pace are controlled by natural-language instructions in the
prompt (there is no ``speed`` parameter like OpenAI's).
"""

from __future__ import annotations

import io
import re
import wave

from google import genai
from google.genai import types

from .config import Settings


def _rate_from_mime(mime: str | None, default: int = 24_000) -> int:
    """Sample rate comes embedded in the mime type, e.g. ``audio/L16;rate=24000``."""
    match = re.search(r"rate=(\d+)", mime or "")
    return int(match.group(1)) if match else default


def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # s16le
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


class GeminiTTSClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = genai.Client(api_key=settings.api_key)

    def synthesize_wav(self, text: str) -> bytes:
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self._settings.voice,
                    )
                )
            ),
        )
        prompt = f"{self._settings.instructions}\n\n{text}"
        response = self._client.models.generate_content(
            model=self._settings.model,
            contents=prompt,
            config=config,
        )
        pcm, rate = self._extract_audio(response)
        return _pcm_to_wav(pcm, rate)

    def _extract_audio(self, response: types.GenerateContentResponse) -> tuple[bytes, int]:
        for candidate in response.candidates or []:
            parts = candidate.content.parts if candidate.content else None
            for part in parts or []:
                blob = part.inline_data
                if blob is not None and blob.data:
                    return blob.data, _rate_from_mime(blob.mime_type)
        raise RuntimeError(
            f"Gemini returned no audio (model={self._settings.model!r}); "
            "check that the model supports AUDIO output"
        )
