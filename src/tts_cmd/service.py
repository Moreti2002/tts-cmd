"""High-level TTS service: orchestrates the activation cue, streamed TTS
fetch, and playback — with cooperative cancellation so a second hotkey
press cleanly stops in-flight speech.

Design notes
------------
* The OpenAI streaming request and the activation cue run **concurrently**
  inside ``speak()``. While the cue plays (~280 ms), the first PCM chunks
  buffer into a ``Queue``, so by the time the cue ends, speech can start
  with zero extra wait.
* A single ``threading.Lock`` guards transitions of the active worker /
  player so ``trigger()`` and ``cancel()`` can be called from any thread
  (e.g. the HTTP daemon's request handlers).
"""

from __future__ import annotations

import queue
import sys
import threading
from typing import Optional

from .audio import PcmStreamPlayer, play_wav
from .config import ACTIVATION_SOUND_PATH, Settings, load_settings
from .sound_effects import generate_activation_sound
from .tts_client import OpenAITTSClient


MAX_TEXT_LENGTH = 4_000  # OpenAI TTS hard limit is 4096 chars.
_SENTINEL = object()


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
        self._client = OpenAITTSClient(self._settings)
        _ensure_activation_sound()

        self._lock = threading.Lock()
        self._worker: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()
        self._current_player: Optional[PcmStreamPlayer] = None

    # ------------------------------------------------------------------ public

    def is_active(self) -> bool:
        with self._lock:
            return self._worker is not None and self._worker.is_alive()

    def cancel(self) -> bool:
        """Stop in-progress speech. Returns True if something was stopped."""
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                return False
            self._cancel_event.set()
            player = self._current_player
        if player is not None:
            player.terminate()
        return True

    def trigger(self, text: str) -> str:
        """Hotkey semantics: if speaking, stop; else, speak ``text``.

        Returns ``"stopped"`` or ``"started"`` for the caller's bookkeeping.
        """
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
            self._current_player = None
            self._worker = threading.Thread(
                target=self._run, args=(text,), daemon=True
            )
            self._worker.start()

    def _run(self, text: str) -> None:
        chunks: "queue.Queue[object]" = queue.Queue(maxsize=64)

        fetcher = threading.Thread(
            target=self._fetch, args=(text, chunks), daemon=True
        )
        fetcher.start()

        # The activation cue plays while the API request warms up. ~280 ms of
        # masking that doubles as user feedback.
        play_wav(ACTIVATION_SOUND_PATH)
        if self._cancel_event.is_set():
            return

        try:
            player = PcmStreamPlayer(sample_rate=self._settings.sample_rate)
        except Exception as exc:  # noqa: BLE001
            print(f"[tts-cmd] audio init failed: {exc}", file=sys.stderr)
            return

        with self._lock:
            self._current_player = player
        try:
            with player:
                while True:
                    if self._cancel_event.is_set():
                        break
                    try:
                        item = chunks.get(timeout=15.0)
                    except queue.Empty:
                        break
                    if item is _SENTINEL:
                        break
                    player.write(item)  # type: ignore[arg-type]
        finally:
            with self._lock:
                self._current_player = None

    def _fetch(self, text: str, chunks: "queue.Queue[object]") -> None:
        try:
            for chunk in self._client.stream(text):
                if self._cancel_event.is_set():
                    break
                chunks.put(chunk)
        except Exception as exc:  # noqa: BLE001
            print(f"[tts-cmd] fetch error: {exc}", file=sys.stderr)
        finally:
            chunks.put(_SENTINEL)
