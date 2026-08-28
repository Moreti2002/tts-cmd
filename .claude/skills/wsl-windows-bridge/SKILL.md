---
name: wsl-windows-bridge
description: >-
  Hard-won patterns for building WSL apps that integrate with the Windows
  desktop — audio playback, global hotkeys, clipboard, notifications, and
  controlling Windows processes from WSL. Use this skill WHENEVER a task
  running in WSL needs to reach the Windows side: playing sound, reacting to
  a keyboard shortcut pressed in any Windows app, reading/writing the Windows
  clipboard, launching or killing a Windows process, resolving Windows paths,
  or running a background daemon under systemd that calls Windows executables.
  Reach for it even if the user just says "make it beep", "play a sound",
  "add a hotkey", or "it works in my shell but not as a service" — those are
  exactly the cases where the non-obvious WSLg/interop gotchas below bite.
  Só se aplica quando a sessão roda dentro do WSL; em Linux nativo, ignore.
---

# WSL ↔ Windows desktop integration

Building something in WSL that has to touch the Windows desktop looks simple
until it isn't. The Linux side reports success, every command exits 0, and yet
nothing is audible, the hotkey does nothing, or the service that worked in your
shell fails under systemd. This skill collects the specific traps and the
patterns that actually work, learned the hard way.

The meta-lesson: **WSL's success signals lie about the Windows side.** A
PulseAudio sink can be `RUNNING` with nothing audible; a curl can exit 0 from
your shell but the daemon never gets the request; `powershell.exe` resolves
interactively but not under systemd. So when integrating across the boundary,
**verify at the Windows endpoint, not the WSL midpoint.**

## Start here: which problem are you solving?

- **Sound / audio playback** → read `references/audio.md`. The headline:
  WSLg PulseAudio is frequently silent at the Windows speaker even when WSL
  thinks it's playing. Play through Windows instead.
- **Global hotkey from any Windows app** → read `references/hotkeys-ahk.md`.
  AutoHotkey v2 + a tiny HTTP call into a WSL daemon. Has subtle syntax and
  quoting traps that silently break the hotkey.
- **Paths, processes, clipboard, systemd PATH** → read `references/interop.md`.
  The plumbing: converting paths, killing Windows processes from WSL, and the
  PATH that a `systemd --user` service does *not* inherit.

Read the relevant reference file before writing code — each one contains
working, copy-adaptable patterns and the exact failure mode each guards
against. This project (`tts-cmd`) is itself a worked reference; its
`src/tts_cmd/windows_audio.py`, `windows/tts_hotkey.ahk`, and
`systemd/tts-cmd.service` embody these patterns.

## The five traps that cost the most time

These recur across audio, hotkeys, and services. Internalize them and most of
the pain disappears.

### 1. WSLg audio can be silent while reporting success

`pactl` shows the RDPSink `RUNNING`, unmuted, 100% volume; `paplay`/`ffplay`
exit 0 — and the speaker stays silent, because WSLg's RDP audio channel isn't
reaching the Windows output device. Meanwhile native Windows audio works fine.
A `wsl --shutdown` sometimes rebinds it, but that kills every WSL process
(including your agent session), so it's not a usable fix mid-work.

**Rule:** don't trust WSL-side audio indicators. To confirm sound actually
reaches the user, play a *sustained* tone (~10 s) and ask — short clips get
missed and "I didn't hear it" gets misattributed to volume. When in doubt,
route audio through Windows (see `references/audio.md`).

### 2. systemd --user has a minimal PATH — Windows .exe names won't resolve

Your interactive shell has `/mnt/c/WINDOWS/system32` etc. on PATH, so
`powershell.exe`, `taskkill.exe`, `curl.exe` "just work". A `systemd --user`
service does **not** inherit that PATH, so the same code throws
`FileNotFoundError: 'powershell.exe'` only once it's a service. Add the Windows
dirs to the unit's `Environment=PATH=…` (see `references/interop.md`). This is
the classic "works in my shell, breaks as a daemon" cause.

### 3. cmd.exe strips the outer quotes of `cmd /c "…" > file`

`cmd.exe /c "C:\path\tool.exe" args > "C:\out.log"` mis-parses: cmd's quote
rule removes the first and last quote of the line, mangling the command, and
the redirect file often never appears. Avoid wrapping in `cmd /c` to capture
output. Prefer tools' own file-output flags (e.g. curl's `--trace-ascii FILE`,
`-o FILE`) or launch the .exe directly. If you must use `cmd /c`, wrap the
whole command in an extra pair of quotes: `cmd /c " "tool" args > "out" "`.

### 4. AutoHotkey v2 silently dies on a syntax error — the hotkey never arms

A malformed line (a classic: a multi-line `=>` fat-arrow in a tray-menu
handler) is a *load-time* error. The process may still appear to be running,
but no hotkey is registered, so pressing it does nothing with no feedback.
Keep handlers on one line, use named functions, and after deploying, confirm
the script actually loaded (write a load-marker to a log, or show a TrayTip).

### 5. Quoting user text through shell layers corrupts it — stage a file

Passing a selection (which may contain quotes, newlines, accents, emoji)
through AHK → cmd → bash → Python quoting is a guaranteed source of breakage.
**Stage the text as a UTF-8 temp file and pass the path**, or POST it as a
raw request body. Never try to escape arbitrary text through nested shells.

## Debugging methodology: isolate every layer

When a cross-boundary feature "doesn't work", the failure could be in any of
several layers, and the symptom (silence, nothing happens) is identical for
all of them. Resist guessing. Instrument each hop and find exactly where the
signal dies. For a hotkey-driven WSL audio feature the layers are:

1. **Did the hotkey fire?** (AHK) — log a line on each keypress.
2. **Did the request reach the daemon?** (Windows→WSL localhost) — log every
   inbound request; test the exact command from PowerShell too.
3. **Did synthesis/work succeed?** (the daemon's job) — log results/sizes.
4. **Did playback/output run?** (the player subprocess) — capture its exit
   code and stderr; don't `-o NUL`/`DEVNULL` while debugging.
5. **Was it actually perceptible?** (Windows endpoint) — a sustained tone the
   user confirms, decoupled from all the logic above.

Add logging at each hop *first*, reproduce once, then read top-to-bottom for
the first silent layer. This converts "it doesn't work" into "layer 3 of 5
succeeds, layer 4 errors with X" in a single reproduction. Several of this
project's bugs (WAV header rejected by SoundPlayer, systemd PATH, WSLg
silence) were only distinguishable this way — they all looked like "no sound".

## Architectural default for these integrations

The pattern that proved robust: a **long-lived WSL daemon** (HTTP on
loopback, kept up by `systemd --user` with linger) does the real work and
holds expensive clients warm; a **thin Windows-side trigger** (AHK firing a
`curl` POST) captures the desktop event; and **output is produced on whichever
side actually reaches the user** — for audio, that's the Windows side. This
keeps per-event latency low (a loopback POST is single-digit ms) and sidesteps
WSLg's unreliable media path. The reference files show each piece.
