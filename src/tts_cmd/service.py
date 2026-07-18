"""High-level TTS service: orchestrates the activation cue, TTS synthesis,
and Windows-side playback — with cooperative cancellation so a second hotkey
press cleanly stops in-flight speech.

Why Windows-side playback?
--------------------------
WSLg's PulseAudio bridge does not reliably reach the Windows output device
on this setup (PulseAudio reports RUNNING but nothing is audible), whereas
native Windows playback works. So speech is synthesized in WSL as a complete
WAV and handed to :mod:`windows_audio`, which plays it through PowerShell's
``System.Media.SoundPlayer``.

Latency note: SoundPlayer needs a full WAV, so we wait for synthesis to
complete before playback starts. The activation cue (played immediately on
the Windows side) masks that ~1-2 s synthesis window.
"""

from __future__ import annotations

import logging
import threading
import platform
from typing import Optional

from .config import ACTIVATION_SOUND_PATH, Settings, load_settings
from .sound_effects import generate_activation_sound
from .tts_client import create_client
from .windows_audio import WindowsAudioBackend
from .linux_audio import LinuxAudioBackend

log = logging.getLogger("tts_cmd.service")

MAX_TEXT_LENGTH = 4_000  # Safety cap (OpenAI's hard limit is 4096 chars).


def _ensure_activation_sound() -> None:
    if not ACTIVATION_SOUND_PATH.is_file():
        generate_activation_sound(ACTIVATION_SOUND_PATH)


def _clean(text: str) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) > MAX_TEXT_LENGTH:
        cleaned = cleaned[:MAX_TEXT_LENGTH].rsplit(" ", 1)[0] + "…"
    return cleaned


class TTSService:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or load_settings()
        self._client = create_client(self._settings)
        _ensure_activation_sound()

        if "microsoft" in platform.uname().release.lower():
            self._audio = WindowsAudioBackend(ACTIVATION_SOUND_PATH)
        else:
            self._audio = LinuxAudioBackend(ACTIVATION_SOUND_PATH)

        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()

    # ------------------------------------------------------------------ public

    def is_active(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    def cancel(self) -> bool:
        """Stop in-progress speech. Returns True if something was stopped."""
        with self._lock:
            active = self._worker is not None and self._worker.is_alive()
            if active:
                self._cancel_event.set()
        if active:
            self._audio.cancel()
        return active

    def trigger(self, text: str) -> str:
        """Hotkey semantics: if speaking, stop; else, speak ``text``."""
        if self.cancel():
            return "stopped"
        cleaned = _clean(text)
        if not cleaned:
            return "empty"
        self._spawn(cleaned)
        return "started"

    def speak(self, text: str) -> int:
        """Blocking speak — used by the CLI path. Returns exit code."""
        cleaned = _clean(text)
        if not cleaned:
            return 2
        self._spawn(cleaned)
        worker = self._worker
        if worker is not None:
            worker.join()
        return 0

    # ----------------------------------------------------------------- private

    def _spawn(self, text: str) -> None:
        with self._lock:
            self._cancel_event.clear()
            self._worker = threading.Thread(target=self._run, args=(text,), daemon=True)
            self._worker.start()

    def _run(self, text: str) -> None:
        log.debug("worker: start (%d chars)", len(text))

        # Cue plays immediately on the Windows side and masks synthesis latency.
        self._audio.play_cue()

        try:
            wav = self._client.synthesize_wav(text)
        except Exception as exc:  # noqa: BLE001
            log.exception("worker: synthesis failed: %s", exc)
            return

        if self._cancel_event.is_set():
            log.debug("worker: cancelled before playback")
            return

        try:
            self._audio.play_speech_wav(wav)
        except Exception as exc:  # noqa: BLE001
            log.exception("worker: playback failed: %s", exc)
        finally:
            log.debug("worker: end")
