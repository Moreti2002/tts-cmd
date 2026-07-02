"""Linux-side audio playback backend.

Plays audio locally using standard Linux tools (paplay or ffplay).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from .windows_audio import sanitize_wav

log = logging.getLogger("tts_cmd.linux_audio")


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


class LinuxAudioBackend:
    """Plays WAV audio natively on Linux."""

    def __init__(self, cue_wav: Path) -> None:
        self._cue_wav = cue_wav
        self._lock = threading.Lock()
        self._speech_proc: Optional[subprocess.Popen] = None
        log.info("Linux audio backend ready")

    def play_cue(self) -> None:
        """Fire-and-forget playback of the short activation cue."""
        if not self._cue_wav.is_file():
            return
            
        if _have("paplay"):
            cmd = ["paplay", str(self._cue_wav)]
        elif _have("ffplay"):
            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(self._cue_wav)]
        elif _have("aplay"):
            cmd = ["aplay", "-q", str(self._cue_wav)]
        else:
            log.warning("No audio player found for cue playback (need paplay, ffplay, or aplay)")
            return

        try:
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("cue playback failed: %s", exc)

    def play_speech_wav(self, wav_bytes: bytes) -> None:
        """Play WAV synchronously from memory. Blocks until finished."""
        if _have("paplay"):
            cmd = ["paplay"]
        elif _have("ffplay"):
            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", "-"]
        elif _have("aplay"):
            cmd = ["aplay", "-q"]
        else:
            log.error("No audio player found for speech playback (need paplay, ffplay, or aplay)")
            return

        # Sanitize WAV just in case, similar to Windows backend
        clean_wav = sanitize_wav(wav_bytes)

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            with self._lock:
                self._speech_proc = proc

            if proc.stdin:
                proc.stdin.write(clean_wav)
                proc.stdin.close()
                
            proc.wait()
        except Exception as exc:  # noqa: BLE001
            log.exception("speech playback failed: %s", exc)
        finally:
            with self._lock:
                self._speech_proc = None

    def cancel(self) -> None:
        """Stop in-progress speech playback, if any."""
        with self._lock:
            proc = self._speech_proc
        if proc is None:
            return
        
        try:
            proc.kill()
        except Exception:
            pass
