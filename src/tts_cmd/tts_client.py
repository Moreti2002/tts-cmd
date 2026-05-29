"""OpenAI TTS streaming client.

Uses the streaming response API so PCM bytes start arriving as soon as the
model produces them — much lower perceived latency than waiting for a full
file. PCM output (s16le @ 24kHz mono) is the right choice because it can be
piped directly into ``ffplay`` with no decoding step.
"""

from __future__ import annotations

from typing import Iterator

from openai import OpenAI

from .config import Settings


class OpenAITTSClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = OpenAI(api_key=settings.openai_api_key)

    def synthesize_wav(self, text: str) -> bytes:
        """Return a complete WAV file for ``text``.

        Used by the Windows-playback backend, which needs a full WAV (with
        header) for ``System.Media.SoundPlayer``. The activation cue masks
        the synthesis latency on the client side.
        """
        request_kwargs = {
            "model": self._settings.model,
            "voice": self._settings.voice,
            "input": text,
            "response_format": "wav",
            "speed": self._settings.speed,
        }
        if self._settings.model.startswith("gpt-4o"):
            request_kwargs["instructions"] = self._settings.instructions

        response = self._client.audio.speech.create(**request_kwargs)
        return response.content

    def stream(self, text: str) -> Iterator[bytes]:
        """Yield raw PCM chunks for the given text.

        The ``with_streaming_response`` form opens a connection and surfaces
        bytes as they arrive on the wire — important for a hotkey-driven TTS
        where every 100 ms of head-of-line delay is noticeable.
        """
        request_kwargs = {
            "model": self._settings.model,
            "voice": self._settings.voice,
            "input": text,
            "response_format": self._settings.response_format,
        }
        # ``instructions`` is only valid on gpt-4o*-tts models — skip it for
        # the legacy tts-1 family so the request stays compatible.
        if self._settings.model.startswith("gpt-4o"):
            request_kwargs["instructions"] = self._settings.instructions

        with self._client.audio.speech.with_streaming_response.create(
            **request_kwargs
        ) as response:
            for chunk in response.iter_bytes(chunk_size=4096):
                if chunk:
                    yield chunk
