# tts-cmd

Hotkey-driven text-to-speech for WSL. Press `Ctrl+Shift+Space` anywhere on
Windows (Chrome, Claude Code terminal, any app) and the selected text is read
aloud by OpenAI's `gpt-4o-mini-tts` model. Press the same hotkey again while
it is speaking to stop it.

A long-running HTTP daemon in WSL holds the OpenAI client warm; the hotkey
fires a sub-100 ms `curl` POST. Audio is played back on the Windows side via
`System.Media.SoundPlayer`, which is reliable regardless of the WSLg audio
bridge state.

## Architecture

```
  Windows                                  WSL
  -------                                  ---
  AHK hotkey  --(curl POST localhost)-->   HTTP daemon
       |                                        |
       | copies selection to                    +--> OpenAI gpt-4o-mini-tts (WAV)
       | a UTF-8 temp file                       |
       |                                         v
       |                                   writes WAV to %TEMP%
       |                                         |
       v                                         v
  SoundPlayer  <--(powershell.exe play)----  daemon invokes powershell.exe
```

* The daemon (`tts_cmd --serve`) listens on `127.0.0.1:47284`.
* `POST /trigger` with the selection as the body. If already speaking, the
  call cancels current playback (toggle semantics). Otherwise it plays the
  activation cue, synthesizes the text to a WAV, writes it to the Windows
  `%TEMP%`, and plays it via `powershell.exe` + `System.Media.SoundPlayer`.
* Playback runs on Windows because WSLg's PulseAudio bridge does not reliably
  reach the Windows output device on all setups (PulseAudio reports `RUNNING`
  but nothing is audible). Routing through Windows avoids that entirely.
* Cancellation: the player PowerShell records its own PID; a second hotkey
  press triggers `taskkill.exe /F /PID` to stop it.
* A `systemd --user` unit (`tts-cmd.service`) keeps the daemon up across
  WSL restarts.

## Requirements

* WSL 2 with Windows interop enabled (`powershell.exe` reachable from WSL).
* Linux: `python3`, `curl`. `ffmpeg` optional (only used to regenerate the
  activation cue from scratch — a prebuilt WAV ships in `assets/`).
* `systemd --user` with linger enabled (`loginctl enable-linger $USER`).
* Windows: AutoHotkey v2.
* An `OPENAI_API_KEY` available in `~/linux-config/.env` (or the daemon's
  environment).

## Install

```bash
git clone https://github.com/Moreti2002/tts-cmd.git
cd tts-cmd
./install.sh
```

The installer:

1. Creates `./venv` and installs `requirements.txt`.
2. Regenerates `assets/activation.wav` (a short tech cue, built at install
   time from `sound_effects.py`).
3. Symlinks the launcher into `~/linux-config/bin/tts_speak_claude`.
4. Installs and starts `~/.config/systemd/user/tts-cmd.service`.

### Windows hotkey

Install AutoHotkey v2, then run `windows/tts_hotkey.ahk` (double-click).
To auto-start on login, drop a shortcut into `shell:startup` (Win+R then
`shell:startup`). The repo path under WSL is visible from Windows as
`\\wsl$\Ubuntu\home\<user>\...\tts-cmd\windows\tts_hotkey.ahk`.

## Usage

| Action                          | Hotkey / command                            |
|---------------------------------|---------------------------------------------|
| Speak current selection         | `Ctrl+Shift+Space`                          |
| Stop in-progress speech         | `Ctrl+Shift+Space` (while speaking)         |
| Speak literal text from WSL     | `tts_speak "hello"`                         |
| Speak text from stdin           | `echo hello \| tts_speak -`                 |
| Speak text from file            | `tts_speak --file /tmp/x.txt`               |
| Cancel from WSL                 | `tts_speak --stop`                          |
| Skip daemon (debug, blocking)   | `tts_speak --direct "hello"`                |

## Configuration

Read from `~/linux-config/.env` (or any environment source the daemon
inherits — `systemd-run --user --setenv` works too).

| Variable          | Default            | Notes                                 |
|-------------------|--------------------|---------------------------------------|
| `OPENAI_API_KEY`  | (required)         |                                       |
| `TTS_MODEL`       | `gpt-4o-mini-tts`  | Any OpenAI TTS model.                 |
| `TTS_VOICE`       | `coral`            | `alloy`, `ash`, `nova`, `shimmer`, …  |
| `TTS_SPEED`       | `1.4`              | Playback rate, `0.25`–`4.0`.          |
| `TTS_HOST`        | `127.0.0.1`        | Loopback by default.                  |
| `TTS_PORT`        | `47284`            |                                       |

## Layout

```
tts-cmd/
├── assets/activation.wav    generated tech cue
├── scripts/tts_speak        CLI wrapper (talks to daemon, fallback to direct)
├── src/tts_cmd/             Python package
│   ├── __main__.py          CLI (--serve, --generate-sound, text args)
│   ├── daemon.py            HTTP server (port 47284)
│   ├── service.py           cancel-aware TTS orchestrator
│   ├── tts_client.py        OpenAI client (WAV + streaming)
│   ├── windows_audio.py     Windows-side playback (SoundPlayer)
│   ├── audio.py             WSL ffplay/paplay fallback
│   ├── sound_effects.py     activation cue generator
│   └── config.py            settings + .env loader
├── systemd/tts-cmd.service  user unit
├── windows/tts_hotkey.ahk   AutoHotkey v2 hotkey
├── install.sh               one-shot setup
└── requirements.txt
```

## Operations

```bash
systemctl --user status tts-cmd.service
systemctl --user restart tts-cmd.service
journalctl --user -u tts-cmd.service -f
curl -s http://127.0.0.1:47284/health
```

## Troubleshooting

| Symptom                                  | Fix                                                                 |
|------------------------------------------|---------------------------------------------------------------------|
| No sound at all                          | Check Windows volume/mixer. Playback uses `powershell.exe` SoundPlayer. |
| `powershell.exe: not found` on daemon    | Ensure the unit's PATH includes the Windows system dirs (see unit). |
| `OPENAI_API_KEY not set`                 | Add it to `~/linux-config/.env`.                                    |
| Hotkey does nothing                      | Check the AHK process is running and `curl /health` answers `ok`.   |
| Daemon crashes on start                  | `journalctl --user -u tts-cmd.service -n 50`.                       |

## License

MIT.
