# Audio playback from WSL

## The core problem

WSLg exposes PulseAudio at `unix:/mnt/wslg/PulseServer`, and in principle
`paplay`/`ffplay` route through it to the Windows speakers. In practice this
bridge is unreliable: on affected setups the `RDPSink` shows `RUNNING`,
unmuted, full volume, and players exit 0 — but **no sound reaches the Windows
output device**. Native Windows audio (e.g. `Media.SoundPlayer`,
`[Console]::Beep`) works fine on the same machine.

Don't burn time trying to fix WSLg audio from inside WSL. The reliable fix is
to **play on the Windows side**, which is as dependable as any native Windows
app.

## Confirm the diagnosis before re-architecting

Two quick checks distinguish "WSLg audio broken" from "Windows muted":

```bash
# 1. Native Windows audio — does the user hear THIS?
powershell.exe -NoProfile -Command "[Console]::Beep(1000,600)"
powershell.exe -NoProfile -Command "(New-Object Media.SoundPlayer 'C:\Windows\Media\notify.wav').PlaySync()"

# 2. A sustained tone through the WSL path — does the user hear THIS?
ffplay -nodisp -autoexit -loglevel quiet -f lavfi -i "sine=frequency=1000:duration=10"
```

If (1) is audible and (2) is not, WSLg audio is the culprit → play through
Windows. Use a *long* tone; short clips get missed and produce false "I heard
nothing" reports. (And always rule out the obvious first: the user's Windows
volume/mixer.)

## Pattern: play a WAV through Windows

Write the WAV to the Windows `%TEMP%` (reachable from WSL via `/mnt/c/...`) and
play it with PowerShell's `System.Media.SoundPlayer`.

```python
import subprocess
from pathlib import Path

def resolve_windows_temp() -> tuple[str, Path]:
    win = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "[Console]::Out.Write($env:TEMP)"],
        capture_output=True, text=True, timeout=8,
    ).stdout.strip()                                  # C:\Users\me\AppData\Local\Temp
    wsl = subprocess.run(["wslpath", win], capture_output=True, text=True).stdout.strip()
    return win, Path(wsl)

def play_wav_windows(win_temp: str, wsl_temp: Path, wav_bytes: bytes) -> None:
    (wsl_temp / "clip.wav").write_bytes(wav_bytes)    # write via the /mnt path
    win_path = f"{win_temp}\\clip.wav"                # play via the Windows path
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         f"(New-Object Media.SoundPlayer '{win_path}').PlaySync()"],
        check=False,
    )
```

`PlaySync()` blocks until the clip finishes; drop the `.run` wait (use `Popen`)
for fire-and-forget cues.

## Trap: SoundPlayer rejects streamed/placeholder WAV headers

Many APIs (including OpenAI's TTS with `response_format="wav"`) stream WAV with
**placeholder chunk sizes** — the RIFF size and `data` size are written as
`0xFFFFFFFF` because the total length isn't known when streaming starts.
`ffplay` tolerates this; `System.Media.SoundPlayer` does **not** — it throws
*"… is not a valid wave file."*

Fix: rewrite the header with correct sizes before handing it to SoundPlayer.
Extract the PCM payload and re-emit via Python's `wave` module, which writes
correct sizes:

```python
import io, struct, wave

def sanitize_wav(raw: bytes) -> bytes:
    data_idx = raw.find(b"data")
    fmt_idx  = raw.find(b"fmt ")
    if data_idx == -1 or fmt_idx == -1:
        return raw
    channels = struct.unpack_from("<H", raw, fmt_idx + 10)[0]
    rate     = struct.unpack_from("<I", raw, fmt_idx + 12)[0]
    bits     = struct.unpack_from("<H", raw, fmt_idx + 22)[0]
    pcm      = raw[data_idx + 8:]                     # data size field is bogus; take to EOF
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels or 1)
        w.setsampwidth((bits or 16) // 8)
        w.setframerate(rate or 24_000)
        w.writeframes(pcm)
    return buf.getvalue()
```

You can verify a WAV is acceptable to SoundPlayer without playing it:

```bash
powershell.exe -NoProfile -Command \
  "try { New-Object Media.SoundPlayer 'C:\path\clip.wav' | Out-Null; 'valid' } \
   catch { 'ERR: ' + \$_.Exception.Message }"
```

## Trap: streaming for low latency doesn't help if it's inaudible

A natural instinct is to stream PCM into `ffplay` for low first-byte latency.
But if WSLg audio is silent, streaming buys nothing. Windows `SoundPlayer`
needs a *complete* WAV, so playback waits for full synthesis (~1–2 s for a
sentence). Mask that with an instant activation cue played on the Windows side,
and accept the small latency in exchange for audio that actually plays.

## Cancelling Windows-side playback from WSL

`SoundPlayer.PlaySync()` blocks its PowerShell process; to stop playback,
kill that process. Have the player record its own PID, then `taskkill` it:

```python
# launch: player writes its Windows PID to a file, then blocks on PlaySync
script = (f"$PID | Set-Content -Encoding ascii '{win_pid_file}'; "
          f"(New-Object Media.SoundPlayer '{win_wav}').PlaySync()")
proc = subprocess.Popen(["powershell.exe", "-NoProfile", "-Command", script])

# cancel: read the recorded PID and force-kill it on the Windows side
pid = Path(wsl_pid_file).read_text().strip().strip("﻿\r\n ")  # note the BOM strip
subprocess.run(["taskkill.exe", "/F", "/PID", pid], check=False)
proc.kill()
```

Strip a possible UTF-8 BOM (`﻿`) and CR from the PID file — PowerShell's
`Set-Content` can add both, and `taskkill` rejects a PID string with stray
bytes.

## Generating an activation cue without external assets

A short "tech" cue can be synthesized with numpy and written as a WAV (sine
blips + a frequency sweep, sharp attack / exponential release). See this
project's `src/tts_cmd/sound_effects.py` for a complete generator. Generating
it at install time avoids shipping a binary asset and keeps it tweakable.
