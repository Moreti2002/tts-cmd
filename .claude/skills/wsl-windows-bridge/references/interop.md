# WSL ↔ Windows interop plumbing

The mechanics underneath audio and hotkeys: paths, processes, localhost, and
the systemd PATH gap.

## Running Windows executables from WSL

WSL's binfmt interop lets you run Windows `.exe` files directly:
`powershell.exe`, `curl.exe`, `taskkill.exe`, etc. Interactively they resolve
because `/mnt/c/WINDOWS/system32` and friends are on your shell PATH. Two
caveats bite later:

- **Prefer full paths in unattended contexts** (`A_WinDir\System32\curl.exe`
  in AHK, or absolute paths in a service) — bare names depend on PATH.
- **`systemd --user` has a minimal PATH** (see below).

## Path conversion

`wslpath` converts both directions — use it, don't hand-roll:

```bash
wslpath 'C:\Users\me\AppData\Local\Temp'   # -> /mnt/c/Users/me/AppData/Local/Temp
wslpath -w /home/me/file.txt               # -> \\wsl$\...  (Windows view of a WSL path)
```

Resolve the Windows `%TEMP%` at runtime rather than hardcoding the username:

```bash
WIN_TEMP=$(powershell.exe -NoProfile -Command "[Console]::Out.Write(\$env:TEMP)")
WSL_TEMP=$(wslpath "$WIN_TEMP")
```

Write files from WSL via the `/mnt/c/...` path; hand the `C:\...` path to
Windows programs. A file staged under the Windows `%TEMP%` is visible to both.
Prefer the Windows-native temp over `\\wsl$\...` for Windows programs — UNC
access into the WSL filesystem is slower and occasionally flaky.

## Killing a Windows process from WSL

You can't `kill` a Windows PID from WSL. Use `taskkill.exe`:

```bash
taskkill.exe /F /PID 12345
```

To get the PID of something you launched, have it record its own `$PID` to a
file (PowerShell `Set-Content`), then read it from WSL. Strip a possible UTF-8
BOM and CR — `Set-Content` may prepend `﻿` / append `\r`, and `taskkill`
rejects a dirty PID string:

```python
pid = Path(pid_file).read_text().strip().strip("﻿\r\n ")
```

## Windows → WSL localhost

WSL2 forwards Windows `127.0.0.1:<port>` to a WSL listener on the same port, so
a daemon bound to `127.0.0.1` inside WSL is reachable from Windows
`curl.exe http://127.0.0.1:<port>/...`. This is the basis of the
hotkey→daemon call. To debug reachability independent of AHK, run the exact
curl from PowerShell:

```bash
powershell.exe -NoProfile -Command \
  'curl.exe -s -o NUL -w "%{http_code}\n" --max-time 2 http://127.0.0.1:47284/health'
```

If PowerShell reaches it but AHK doesn't, the problem is in the AHK script (see
`hotkeys-ahk.md`), not the network.

## systemd --user service that calls Windows executables

A `systemd --user` service is the right way to keep a WSL daemon alive across
terminal closes and WSL restarts. Enable linger so it runs without an open
session:

```bash
loginctl enable-linger "$USER"
```

The trap: the service inherits a **minimal PATH**, so `powershell.exe`,
`taskkill.exe`, and other Windows tools that "just worked" in your shell now
fail with `FileNotFoundError`. Put the Windows system dirs on the unit's PATH,
and pass through the audio/runtime env:

```ini
[Unit]
Description=my WSL daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/me/project
Environment=PYTHONPATH=/home/me/project/src
Environment=XDG_RUNTIME_DIR=/run/user/1000
# Windows interop tools (powershell.exe, taskkill.exe) need these on PATH:
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/lib/wsl/lib:/mnt/c/WINDOWS/system32:/mnt/c/WINDOWS:/mnt/c/WINDOWS/System32/Wbem:/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0
ExecStart=/home/me/project/venv/bin/python -u -m myapp --serve
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

Install and manage:

```bash
cp myapp.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now myapp.service
systemctl --user status myapp.service
journalctl --user -u myapp.service -f         # live logs while debugging
```

## Trap: a signal handler that calls server.shutdown() deadlocks

If a daemon's `SIGTERM` handler calls `server.shutdown()` on a
`ThreadingHTTPServer`, it deadlocks: `shutdown()` blocks until `serve_forever()`
returns, but the handler runs on the very thread that owns `serve_forever()`.
The service then hangs in `deactivating (stop-sigterm)` for the full stop
timeout on every `restart`. Dispatch the shutdown to a helper thread:

```python
def _shutdown(*_):
    service.cancel()
    threading.Thread(target=server.shutdown, daemon=True).start()
signal.signal(signal.SIGTERM, _shutdown)
```

## Capturing a subprocess's real error while debugging

When a Windows program launched from WSL misbehaves, don't discard its output.
Avoid `cmd /c "…" > file` (cmd's quote-stripping mangles it). Use the tool's
own file-output flag — e.g. curl writes a full trace with
`--trace-ascii "C:\path\trace.log"` and an HTTP code with
`-w "%{http_code}"` — or capture `stderr` directly via `subprocess.PIPE`.
Only switch back to `-o NUL` / `DEVNULL` once it's working.
