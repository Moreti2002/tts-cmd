"""Low-latency audio playback helpers.

* ``play_wav(path)``         — synchronous, fire-and-forget playback of a
  short pre-recorded WAV. Used for the activation cue.
* ``PcmStreamPlayer``        — context manager that pipes raw PCM bytes into
  ``ffplay`` as they arrive, so OpenAI's streamed TTS plays with minimal
  buffering delay. Supports ``terminate()`` for hotkey-driven cancellation.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("tts_cmd.audio")


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def play_wav(path: Path) -> None:
    """Block until a short WAV finishes playing. Errors are logged but
    never raised — the activation cue is a nice-to-have, never a blocker."""
    if not path.is_file():
        log.warning("play_wav: %s missing", path)
        return
    try:
        if _have("paplay"):
            cmd = ["paplay", str(path)]
        elif _have("ffplay"):
            cmd = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
        else:
            log.warning("no audio player available (need paplay or ffplay)")
            return
        result = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=5.0,
        )
        if result.returncode != 0:
            log.warning("%s rc=%d stderr=%r", cmd[0], result.returncode,
                        result.stderr.decode("utf-8", "replace")[:200])
    except subprocess.TimeoutExpired:
        log.warning("play_wav timed out")
    except Exception as exc:  # noqa: BLE001
        log.exception("play_wav failed: %s", exc)


class PcmStreamPlayer:
    """Stream raw signed-16-bit little-endian PCM to ffplay via stdin.

    Usage:
        with PcmStreamPlayer(sample_rate=24_000) as player:
            for chunk in tts_stream:
                player.write(chunk)
                if cancelled:
                    player.terminate()
                    break
    """

    def __init__(self, sample_rate: int = 24_000, channels: int = 1) -> None:
        if not _have("ffplay"):
            raise RuntimeError("ffplay not found. Install ffmpeg (apt install ffmpeg).")
        self._sample_rate = sample_rate
        self._channels = channels
        self._proc: subprocess.Popen | None = None
        self._terminated = False

    def __enter__(self) -> "PcmStreamPlayer":
        self._proc = subprocess.Popen(
            [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel", "quiet",
                "-f", "s16le",
                "-ar", str(self._sample_rate),
                "-ac", str(self._channels),
                "-i", "pipe:0",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self

    def write(self, data: bytes) -> None:
        if not data or self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(data)
        except (BrokenPipeError, ValueError, OSError):
            pass

    def terminate(self) -> None:
        """Hard-kill the playback process. Safe to call multiple times."""
        if self._proc is None or self._terminated:
            return
        self._terminated = True
        try:
            self._proc.kill()
        except Exception:
            pass

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin is not None and not self._terminated:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
