; tts_hotkey.ahk — Global Ctrl+Shift+Space binding for the tts-cmd daemon.
;
; First press : speaks the currently selected text via the WSL daemon.
; Second press: stops in-progress speech (text is ignored on the cancel path).
;
; The daemon is a long-running HTTP server in WSL (see systemd/tts-cmd.service)
; — this script only fires a short ``curl.exe`` POST, so hotkey latency stays
; well below 100 ms.

#Requires AutoHotkey v2.0
#SingleInstance Force

DAEMON_URL    := "http://127.0.0.1:47284"
TMP_FILE_NAME := "tts_cmd_input.txt"
CLIP_WAIT_S   := 0.25

WindowsToWslPath(winPath) {
    drive := StrLower(SubStr(winPath, 1, 1))
    rest  := StrReplace(SubStr(winPath, 3), "\", "/")
    return "/mnt/" . drive . rest
}

PostTrigger(tmpFile := "") {
    global DAEMON_URL
    base := 'curl.exe -s -o NUL --max-time 1 -X POST '
         . '-H "Content-Type: text/plain; charset=utf-8" '
    if (tmpFile = "") {
        Run(base . '--data-binary "" "' . DAEMON_URL . '/trigger"', , "Hide")
    } else {
        Run(base . '--data-binary "@' . tmpFile . '" "' . DAEMON_URL . '/trigger"', , "Hide")
    }
}

SpeakSelection() {
    global TMP_FILE_NAME, CLIP_WAIT_S

    savedClip := ClipboardAll()
    A_Clipboard := ""
    Send "^c"
    if !ClipWait(CLIP_WAIT_S, 1) {
        ; No selection — still fire a trigger so a second press while speech
        ; is playing reliably stops it.
        A_Clipboard := savedClip
        PostTrigger()
        return
    }

    text := A_Clipboard
    A_Clipboard := savedClip
    text := Trim(text)
    if (text = "") {
        PostTrigger()
        return
    }

    tmpFile := A_Temp . "\" . TMP_FILE_NAME
    try FileDelete(tmpFile)
    FileAppend(text, tmpFile, "UTF-8")
    PostTrigger(tmpFile)
}

^+Space:: SpeakSelection()

; Tray menu — same UX pattern as stt-hotkey.
A_TrayMenu.Add()
A_TrayMenu.Add("Trigger now", (*) => SpeakSelection())
A_TrayMenu.Add("Stop speech", (*) =>
    Run('curl.exe -s -o NUL --max-time 1 -X POST "' . DAEMON_URL . '/cancel"', , "Hide"))
A_TrayMenu.Add("Reload",      (*) => Reload())
A_TrayMenu.Add("Exit",        (*) => ExitApp())
TraySetIcon("imageres.dll", 198)
A_IconTip := "tts-cmd — Ctrl+Shift+Space"
