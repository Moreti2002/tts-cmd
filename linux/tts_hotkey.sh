#!/usr/bin/env bash
# tts_hotkey.sh - Trigger the TTS daemon on native Linux.
# Map this script to a global hotkey (e.g. Ctrl+Shift+Space) in your DE settings
# (GNOME Settings -> Keyboard -> Custom Shortcuts).
#
# Requirements: wl-clipboard (Wayland) or xclip/xsel (X11) installed.

DAEMON_URL="http://127.0.0.1:47284"

# Try Wayland primary, then X11 primary, then Wayland clipboard, then X11 clipboard
TEXT=$(wl-paste -p 2>/dev/null || xclip -o -selection primary 2>/dev/null || xsel -p -o 2>/dev/null || wl-paste 2>/dev/null || xclip -o -selection clipboard 2>/dev/null)

if [ -z "$TEXT" ]; then
    # Empty trigger to toggle playback off if it's currently speaking
    curl -s -o /dev/null --max-time 3 -X POST "$DAEMON_URL/trigger"
    exit 0
fi

# We have text. Write to a temp file and post.
TMP_FILE=$(mktemp)
echo -n "$TEXT" > "$TMP_FILE"

curl -s -o /dev/null --max-time 3 -X POST -H "Content-Type: text/plain; charset=utf-8" --data-binary "@$TMP_FILE" "$DAEMON_URL/trigger"

rm -f "$TMP_FILE"
