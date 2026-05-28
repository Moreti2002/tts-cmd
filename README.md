# tts-cmd

Hotkey-driven, low-latency text-to-speech for WSL. Press
`Ctrl+Shift+Space` anywhere on Windows (Chrome, Claude Code terminal, any
app) and the selected text is read aloud by OpenAI's `gpt-4o-mini-tts`
model. Press the same hotkey again while it is speaking to stop it.

A long-running HTTP daemon in WSL holds the OpenAI client warm; the hotkey
fires a 7 ms `curl` POST, so the only meaningful wait is the API's
first-byte time.

## Architecture

```
  Windows                                WSL
  -------                                ---
  AHK hotkey  --(curl POST localhost)-->  HTTP daemon  --(PCM stream)-->  ffplay
       \                                       |
        copies selection to                    +--> activation cue (paplay)
        a UTF-8 temp file                      |
                                               +--> OpenAI gpt-4o-mini-tts
```

* The daemon (`tts_cmd --serve`) listens on `127.0.0.1:47284`.
* `POST /trigger` with the selection as the body. If already speaking, the
  call cancels current playback (toggle semantics). Otherwise it kicks off a
  worker that plays the activation cue and streams the TTS PCM straight into
  `ffplay` via a pipe.
* A `systemd --user` unit (`tts-cmd.service`) keeps the daemon up across
  WSL restarts.
* The AHK script (Windows side) only knows how to copy the selection and
  POST it.

## Requirements

* WSL 2 with WSLg (provides PulseAudio at `unix:/mnt/wslg/PulseServer`).
* Linux: `python3`, `ffmpeg` (for `ffplay`), `curl`. `paplay` optional but
  recommended.
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
│   ├── tts_client.py        OpenAI streaming client
│   ├── audio.py             ffplay pipe + WAV playback
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
| No sound at all                          | `pactl info` must report `unix:/mnt/wslg/PulseServer`. Update WSL.  |
| `ffplay: command not found`              | `sudo apt install ffmpeg`                                           |
| `OPENAI_API_KEY not set`                 | Add it to `~/linux-config/.env`.                                    |
| Hotkey does nothing                      | Check the AHK process is running and `curl /health` answers `ok`.   |
| Daemon crashes on start                  | `journalctl --user -u tts-cmd.service -n 50`.                       |

## License

MIT.
