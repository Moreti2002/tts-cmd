"""Windows-side audio playback backend.

WSLg's PulseAudio bridge (RDPSink) is unreliable on this setup — PulseAudio
reports playback as RUNNING but no sound reaches the Windows output device,
while native Windows playback (e.g. ``Media.SoundPlayer``) works fine.

This backend sidesteps WSLg audio entirely: WAV bytes produced in WSL are
written to the Windows ``%TEMP%`` directory (reachable from WSL via the
``/mnt/c`` mount) and played by ``powershell.exe`` through
``System.Media.SoundPlayer``.

Cancellation is handled by having the player PowerShell write its own PID to
a file before blocking on ``PlaySync()``; ``taskkill.exe /F /PID`` then stops
it on demand.
"""

from __future__ import annotations

import io
import logging
import struct
import subprocess
import threading
import wave
from pathlib import Path
from typing import Optional

log = logging.getLogger("tts_cmd.windows_audio")


class WindowsAudioError(RuntimeError):
    pass


def sanitize_wav(raw: bytes) -> bytes:
    """Rewrite a WAV with correct chunk sizes.

    OpenAI streams WAV with placeholder chunk sizes (0xFFFFFFFF) for both the
    RIFF and data chunks. ffplay tolerates this, but Windows
    ``System.Media.SoundPlayer`` rejects it as "not a valid wave file". We
    extract the PCM payload and the format parameters, then re-emit a WAV with
    correct sizes via the ``wave`` module.
    """
    try:
        data_idx = raw.find(b"data")
        fmt_idx = raw.find(b"fmt ")
        if data_idx == -1 or fmt_idx == -1:
            return raw
        # fmt subchunk fields (little-endian), relative to "fmt " marker.
        channels = struct.unpack_from("<H", raw, fmt_idx + 10)[0]
        rate = struct.unpack_from("<I", raw, fmt_idx + 12)[0]
        bits = struct.unpack_from("<H", raw, fmt_idx + 22)[0]
        pcm = raw[data_idx + 8:]

        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(channels or 1)
            w.setsampwidth((bits or 16) // 8)
            w.setframerate(rate or 24_000)
            w.writeframes(pcm)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.warning("sanitize_wav failed (%s); using raw bytes", exc)
        return raw


def _resolve_windows_temp() -> tuple[str, Path]:
    """Return (windows_style_temp, wsl_style_temp). Raises on failure."""
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "[Console]::Out.Write($env:TEMP)"],
            capture_output=True, text=True, timeout=8,
        )
        win_temp = out.stdout.strip()
        if not win_temp:
            raise WindowsAudioError("could not read Windows %TEMP%")
        wsl_temp = subprocess.run(
            ["wslpath", win_temp], capture_output=True, text=True, timeout=8,
        ).stdout.strip()
        wsl_path = Path(wsl_temp)
        if not wsl_path.is_dir():
            raise WindowsAudioError(f"resolved temp dir does not exist: {wsl_temp}")
        return win_temp, wsl_path
    except WindowsAudioError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise WindowsAudioError(f"failed to resolve Windows temp: {exc}") from exc


class WindowsAudioBackend:
    """Plays WAV audio through Windows, bypassing WSLg PulseAudio."""

    def __init__(self, cue_wav_wsl: Path, stop_cue_wav_wsl: Path) -> None:
        self._win_temp, self._wsl_temp = _resolve_windows_temp()

        # Stable filenames inside Windows temp.
        self._cue_win = f"{self._win_temp}\\tts_cmd_cue.wav"
        self._cue_wsl = self._wsl_temp / "tts_cmd_cue.wav"
        self._stop_cue_win = f"{self._win_temp}\\tts_cmd_stop_cue.wav"
        self._stop_cue_wsl = self._wsl_temp / "tts_cmd_stop_cue.wav"
        self._speech_win = f"{self._win_temp}\\tts_cmd_speech.wav"
        self._speech_wsl = self._wsl_temp / "tts_cmd_speech.wav"
        self._pid_win = f"{self._win_temp}\\tts_cmd_play.pid"
        self._pid_wsl = self._wsl_temp / "tts_cmd_play.pid"

        # Copy the cues into Windows temp once.
        for src, dst in ((cue_wav_wsl, self._cue_wsl), (stop_cue_wav_wsl, self._stop_cue_wsl)):
            try:
                if src.is_file():
                    dst.write_bytes(src.read_bytes())
            except Exception as exc:  # noqa: BLE001
                log.warning("could not stage cue %s: %s", src.name, exc)

        self._lock = threading.Lock()
        self._speech_proc: Optional[subprocess.Popen] = None
        log.info("Windows audio backend ready (temp=%s)", self._win_temp)

    # -------------------------------------------------------------- cue

    def play_cue(self) -> None:
        """Fire-and-forget playback of the short activation cue."""
        self._play_cue_file(self._cue_wsl, self._cue_win)

    def play_stop_cue(self) -> None:
        """Fire-and-forget playback of the deactivation cue."""
        self._play_cue_file(self._stop_cue_wsl, self._stop_cue_win)

    def _play_cue_file(self, wsl_path: Path, win_path: str) -> None:
        if not wsl_path.is_file():
            return
        script = f"(New-Object Media.SoundPlayer '{win_path}').PlaySync()"
        try:
            subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-Command", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("cue playback failed: %s", exc)

    # ------------------------------------------------------------ speech

    def play_speech_wav(self, wav_bytes: bytes) -> None:
        """Write WAV to Windows temp and play it synchronously.

        Blocks until playback finishes or is cancelled via ``cancel()``.
        """
        self._speech_wsl.write_bytes(sanitize_wav(wav_bytes))

        # The player writes its own Windows PID, then blocks on PlaySync so we
        # can kill exactly that process to cancel.
        script = (
            f"$PID | Set-Content -Encoding ascii '{self._pid_win}'; "
            f"(New-Object Media.SoundPlayer '{self._speech_win}').PlaySync()"
        )
        try:
            self._pid_wsl.unlink(missing_ok=True)
        except Exception:
            pass

        proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-Command", script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        with self._lock:
            self._speech_proc = proc
        try:
            proc.wait()
        finally:
            with self._lock:
                self._speech_proc = None

    def cancel(self) -> None:
        """Stop in-progress speech playback, if any."""
        with self._lock:
            proc = self._speech_proc
        if proc is None:
            return
        # Kill the Windows player process by the PID it recorded.
        try:
            win_pid = self._pid_wsl.read_text().strip().strip("\r\n﻿")
            if win_pid:
                subprocess.run(
                    ["taskkill.exe", "/F", "/PID", win_pid],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=5,
                )
        except Exception as exc:  # noqa: BLE001
            log.debug("taskkill failed: %s", exc)
        try:
            proc.kill()
        except Exception:
            pass
