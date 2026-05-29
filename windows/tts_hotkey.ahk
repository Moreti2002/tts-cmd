; tts_hotkey.ahk — Global Ctrl+Shift+Space binding for the tts-cmd daemon.
;
; First press : speaks the currently selected text via the WSL daemon.
; Second press: stops in-progress speech.
;
; The daemon is a long-running HTTP server in WSL (systemd/tts-cmd.service).
; This script copies the selection, stages it as a UTF-8 temp file, and fires
; a short curl.exe POST — so hotkey latency stays well below 100 ms.

#Requires AutoHotkey v2.0
#SingleInstance Force

DAEMON_URL    := "http://127.0.0.1:47284"
CURL_EXE      := A_WinDir . "\System32\curl.exe"
TMP_FILE      := A_Temp . "\tts_cmd_input.txt"
CLIP_WAIT_S   := 0.30

PostFile(tmpFile) {
    global DAEMON_URL, CURL_EXE
    Run('"' . CURL_EXE . '" -s -o NUL --max-time 3 -X POST '
        . '-H "Content-Type: text/plain; charset=utf-8" '
        . '--data-binary "@' . tmpFile . '" '
        . '"' . DAEMON_URL . '/trigger"', , "Hide")
}

PostEmpty() {
    global DAEMON_URL, CURL_EXE
    ; Empty trigger: while speaking, this toggles playback off.
    Run('"' . CURL_EXE . '" -s -o NUL --max-time 3 -X POST "'
        . DAEMON_URL . '/trigger"', , "Hide")
}

StopSpeech(*) {
    global DAEMON_URL, CURL_EXE
    Run('"' . CURL_EXE . '" -s -o NUL --max-time 3 -X POST "'
        . DAEMON_URL . '/cancel"', , "Hide")
}

SpeakSelection(*) {
    global TMP_FILE, CLIP_WAIT_S

    savedClip := ClipboardAll()
    A_Clipboard := ""
    Send "^c"
    if !ClipWait(CLIP_WAIT_S, 1) {
        ; No selection captured — still fire a trigger so a second press
        ; reliably stops in-progress speech.
        A_Clipboard := savedClip
        PostEmpty()
        return
    }

    text := Trim(A_Clipboard)
    A_Clipboard := savedClip
    if (text = "") {
        PostEmpty()
        return
    }

    try FileDelete(TMP_FILE)
    FileAppend(text, TMP_FILE, "UTF-8")
    PostFile(TMP_FILE)
}

ReloadScript(*) => Reload()
ExitScript(*)   => ExitApp()

^+Space:: SpeakSelection()

; Tray menu
A_TrayMenu.Add()
A_TrayMenu.Add("Falar selecao agora", SpeakSelection)
A_TrayMenu.Add("Parar fala", StopSpeech)
A_TrayMenu.Add("Recarregar", ReloadScript)
A_TrayMenu.Add("Sair", ExitScript)
TraySetIcon("imageres.dll", 198)
A_IconTip := "tts-cmd — Ctrl+Shift+Space"
