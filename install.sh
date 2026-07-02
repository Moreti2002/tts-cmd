#!/usr/bin/env bash
# install.sh — one-shot setup.
#
# Creates the venv, installs deps, regenerates the activation cue,
# installs the launcher symlink (per ~/linux-config conventions), and
# installs/enables the systemd-user daemon.
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
VENV_DIR="${PROJECT_ROOT}/venv"
LINUX_CONFIG_BIN="${HOME}/linux-config/bin"
SYSTEMD_USER_DIR="${HOME}/.config/systemd/user"

log()  { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
err()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; }

require_cmd() {
    command -v "$1" &>/dev/null || { err "missing required command: $1"; exit 1; }
}

log "checking system dependencies..."
require_cmd python3
require_cmd ffplay
require_cmd curl
command -v paplay &>/dev/null || warn "paplay missing — activation cue will use ffplay"

log "preparing virtualenv at ${VENV_DIR}..."
[[ -d "${VENV_DIR}" ]] || python3 -m venv "${VENV_DIR}"
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -r "${PROJECT_ROOT}/requirements.txt"

log "generating activation sound..."
PYTHONPATH="${PROJECT_ROOT}/src" "${VENV_DIR}/bin/python" -m tts_cmd --generate-sound

log "verifying OPENAI_API_KEY..."
if grep -q '^OPENAI_API_KEY=' "${HOME}/linux-config/.env" 2>/dev/null; then
    log "  found in ~/linux-config/.env"
else
    warn "OPENAI_API_KEY not found in ~/linux-config/.env — set it before first run."
fi

log "installing launcher alias..."
mkdir -p "${LINUX_CONFIG_BIN}"
ln -sf "${PROJECT_ROOT}/scripts/tts_speak" "${LINUX_CONFIG_BIN}/tts_speak_claude"
chmod +x "${PROJECT_ROOT}/scripts/tts_speak"

log "installing systemd-user service..."
mkdir -p "${SYSTEMD_USER_DIR}"
cp "${PROJECT_ROOT}/systemd/tts-cmd.service" "${SYSTEMD_USER_DIR}/tts-cmd.service"
systemctl --user daemon-reload
systemctl --user enable --now tts-cmd.service
sleep 0.5
if curl -s -o /dev/null --max-time 1 http://127.0.0.1:47284/health; then
    log "  daemon healthy on http://127.0.0.1:47284"
else
    warn "daemon not yet responding — check: systemctl --user status tts-cmd.service"
fi

log "done."
cat <<EOF

Next steps:
  1. Smoke test:
       ${PROJECT_ROOT}/scripts/tts_speak "olá, sistema pronto"
  2. Windows Hotkey:
       Run \\\\wsl\$\\Ubuntu${PROJECT_ROOT}/windows/tts_hotkey.ahk with AutoHotkey v2.
       (Drop a shortcut in shell:startup to auto-launch on login.)
  3. Linux Hotkey (Ubuntu/GNOME):
       Map a custom shortcut (like Ctrl+Shift+Space) in your DE settings
       to execute: ${PROJECT_ROOT}/linux/tts_hotkey.sh
EOF
