# tts-cmd

Hotkey-driven text-to-speech for WSL and Native Linux. Press `Ctrl+Shift+Space` anywhere on
Windows or Linux (Chrome, Claude Code terminal, any app) and the selected text is read
aloud by a cloud TTS model (Gemini by default, OpenAI selectable via
`TTS_PROVIDER`). Press the same hotkey again while it is speaking to stop it.

A long-running HTTP daemon holds the TTS client warm; the hotkey
fires a sub-100 ms `curl` POST. When running in WSL, audio is played back on the Windows side via
`System.Media.SoundPlayer`, which is reliable regardless of the WSLg audio
bridge state. On Native Linux, it plays directly using `paplay`, `ffplay` or `aplay`.

## Architecture

```
  Windows                                  WSL
  -------                                  ---
  AHK hotkey  --(curl POST localhost)-->   HTTP daemon
       |                                        |
       | copies selection to                    +--> TTS provider (Gemini/OpenAI, WAV)
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
* An API key for the chosen provider (`GEMINI_API_KEY` or `OPENAI_API_KEY`)
  available in `~/linux-config/.api-keys`, `~/linux-config/.env` or the
  daemon's environment.

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

### Linux hotkey (Ubuntu / GNOME)

Map a custom keyboard shortcut (e.g. `Ctrl+Shift+Space`) to execute the provided script:
```bash
/path/to/tts-cmd/linux/tts_hotkey.sh
```
Requires `wl-clipboard` (Wayland) or `xclip`/`xsel` (X11) installed to read text selection.

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

Read from `~/linux-config/.api-keys`, `~/linux-config/.env` or any
environment source the daemon inherits.

| Variable          | Default             | Notes                                            |
|-------------------|---------------------|--------------------------------------------------|
| `TTS_PROVIDER`    | `gemini`            | `gemini` or `openai`.                            |
| `GEMINI_API_KEY`  | (required if gemini)|                                                  |
| `OPENAI_API_KEY`  | (required if openai)|                                                  |
| `TTS_MODEL`       | per provider        | `gemini-3.1-flash-tts-preview` / `gpt-4o-mini-tts`. |
| `TTS_VOICE`       | per provider        | Gemini: `Kore`, `Puck`, `Zephyr`, … OpenAI: `coral`, `alloy`, … |
| `TTS_SPEED`       | `1.4`               | OpenAI only; Gemini paces via prompt instructions. |
| `TTS_HOST`        | `127.0.0.1`         | Loopback by default.                             |
| `TTS_PORT`        | `47284`             |                                                  |

## Layout

```
tts-cmd/
├── assets/activation.wav    generated tech cue
├── scripts/tts_speak        CLI wrapper (talks to daemon, fallback to direct)
├── src/tts_cmd/             Python package
│   ├── __main__.py          CLI (--serve, --generate-sound, text args)
│   ├── daemon.py            HTTP server (port 47284)
│   ├── service.py           cancel-aware TTS orchestrator
│   ├── tts_client.py        provider-agnostic interface + factory
│   ├── gemini_tts.py        Gemini client (PCM -> WAV)
│   ├── openai_tts.py        OpenAI client (WAV + streaming)
│   ├── windows_audio.py     Windows-side playback (SoundPlayer)
│   ├── linux_audio.py       Native Linux playback (paplay/ffplay/aplay)
│   ├── audio.py             WSL ffplay/paplay fallback
│   ├── sound_effects.py     activation cue generator
│   └── config.py            settings + .env loader
├── systemd/tts-cmd.service  user unit
├── windows/tts_hotkey.ahk   AutoHotkey v2 hotkey for Windows
├── linux/tts_hotkey.sh      Bash trigger script for Ubuntu/GNOME
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
| No sound at all                          | **Windows**: Check Windows volume/mixer. Playback uses `powershell.exe` SoundPlayer.<br>**Linux**: Ensure `pulseaudio-utils` (paplay) or `ffmpeg` (ffplay) is installed. |
| `powershell.exe: not found` on daemon    | **WSL only**: Ensure the unit's PATH includes the Windows system dirs (see unit). |
| `GEMINI_API_KEY not set`                 | Add it to `~/linux-config/.api-keys` (or `.env`).                   |
| Hotkey does nothing                      | Check the AHK process is running (Windows) or the GNOME shortcut (Linux), and `curl 127.0.0.1:47284/health` answers `ok`.   |
| Daemon crashes on start                  | `journalctl --user -u tts-cmd.service -n 50`.                       |

## License

MIT.
