# Global hotkeys from Windows into a WSL daemon

## Why AutoHotkey

WSL can't register a Windows-global keyboard shortcut — the key event happens
in the Windows session, in whatever app has focus (browser, terminal, PDF
viewer). AutoHotkey v2 is the reliable way to capture a system-wide hotkey and
hand it off. Keep the AHK script tiny: capture the event, grab the selection,
and fire a single HTTP call into a long-running WSL daemon. All real logic
lives in the daemon; AHK is just the trigger.

## Capturing the selection without destroying the clipboard

There's no API for "the currently selected text", so simulate Ctrl+C, read the
clipboard, then restore it so the hotkey is non-destructive:

```ahk
SpeakSelection(*) {
    savedClip := ClipboardAll()
    A_Clipboard := ""
    Send "^c"
    if !ClipWait(0.3, 1) {        ; wait up to 300ms for the copy
        A_Clipboard := savedClip
        PostEmpty()               ; no selection — still fire (lets a 2nd press cancel)
        return
    }
    text := Trim(A_Clipboard)
    A_Clipboard := savedClip      ; restore the user's clipboard
    ; ... stage `text` and POST it ...
}
```

## Passing the text safely: stage a UTF-8 file

Do not interpolate the selection into a command line — arbitrary text with
quotes/newlines/accents will break the AHK→cmd→bash→app quoting chain. Write it
to a UTF-8 temp file and pass `--data-binary "@file"`, or POST the raw body.

```ahk
CURL := A_WinDir . "\System32\curl.exe"   ; full path — don't rely on PATH
TMP  := A_Temp . "\myapp_input.txt"

PostFile(tmpFile) {
    Run('"' . CURL . '" -s -o NUL --max-time 3 -X POST '
        . '-H "Content-Type: text/plain; charset=utf-8" '
        . '--data-binary "@' . tmpFile . '" '
        . '"http://127.0.0.1:47284/trigger"', , "Hide")
}

; in SpeakSelection, after capturing `text`:
try FileDelete(TMP)
FileAppend(text, TMP, "UTF-8")
PostFile(TMP)
```

`Run(cmd, , "Hide")` suppresses the console flash. Use the **full path** to
`curl.exe` — AHK's working directory and PATH aren't guaranteed to resolve a
bare `curl.exe`.

## Trap: a syntax error means the hotkey never arms (silently)

AutoHotkey v2 validates the whole script at load. One malformed line and the
hotkey is never registered — but the process may still show as running, so
pressing the key does nothing and there's no error in your face. The classic
offender is a **multi-line fat-arrow** in a tray-menu handler:

```ahk
; BROKEN — fat arrow split across lines can fail to parse, killing the script:
A_TrayMenu.Add("Stop", (*) =>
    Run('curl.exe ...'))

; ROBUST — named function, one statement per line:
StopSpeech(*) {
    Run('"' . CURL . '" -s -o NUL --max-time 3 -X POST "http://127.0.0.1:47284/cancel"', , "Hide")
}
A_TrayMenu.Add("Stop", StopSpeech)
```

After deploying, confirm the script actually loaded — don't assume. During
development, write a marker on load and on each keypress:

```ahk
LogLine(msg) {
    try FileAppend(A_Now . "  " . msg . "`n", A_Temp . "\myapp_hotkey.log", "UTF-8")
}
LogLine("=== script loaded, hotkey registered ===")
^+Space:: SpeakSelection()         ; Ctrl+Shift+Space
```

Then read `%TEMP%\myapp_hotkey.log` from WSL (`/mnt/c/Users/<you>/AppData/Local/Temp/`)
to see whether load and keypresses happened. Remove the logging for the
production version once it's proven.

## Toggle semantics (press again to stop)

Make the daemon's `/trigger` a toggle: if it's currently working, cancel;
otherwise start. Then a no-selection keypress (empty body) still cancels
in-progress work, which is what users expect from a single hotkey. Keep a
separate `/cancel` for the tray menu.

## Deploying and (re)starting the script

Put the `.ahk` in the Windows Startup folder so it auto-runs at login:
`C:\Users\<you>\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\`
(from WSL: `/mnt/c/Users/<you>/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup/`).

To restart after editing, from WSL:

```bash
STARTUP="/mnt/c/Users/<you>/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup"
cp myapp_hotkey.ahk "$STARTUP/myapp-hotkey.ahk"
# kill only THIS script's instance (match the command line), then relaunch
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='AutoHotkey64.exe'\" | Where-Object { \$_.CommandLine -like '*myapp-hotkey*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }"
powershell.exe -NoProfile -Command "Start-Process -FilePath 'C:\Users\<you>\AppData\Local\Programs\AutoHotkey\v2\AutoHotkey64.exe' -ArgumentList '\"<windows-path-to-ahk>\"'"
```

Match on the command line so you don't kill the user's *other* AHK scripts
(they may run several, e.g. a separate STT hotkey on another port).
