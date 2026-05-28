"""Local HTTP daemon that exposes the TTS service to the AHK hotkey.

Endpoints
---------
* ``GET  /health``  — liveness probe; returns ``{"ok": true}``.
* ``POST /trigger`` — body is UTF-8 text to speak. If the service is
  currently speaking, this stops it (text is ignored). Otherwise it starts
  speaking the body.
* ``POST /cancel``  — explicit stop, regardless of body.

The server binds to loopback only and uses ``ThreadingHTTPServer`` so
``/trigger`` calls don't block one another.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import Settings, load_settings
from .service import TTSService

log = logging.getLogger("tts_cmd.daemon")


class _Handler(BaseHTTPRequestHandler):
    service: TTSService  # injected by ``serve()`` via class attribute

    # Silence default access log — systemd-journald already timestamps lines.
    def log_message(self, fmt: str, *args: object) -> None:  # noqa: D401
        log.debug("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return ""
        raw = self.rfile.read(length)
        return raw.decode("utf-8", errors="replace")

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._send_json({"ok": True, "active": self.service.is_active()})
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/trigger":
            text = self._read_body()
            action = self.service.trigger(text)
            self._send_json({"action": action})
        elif self.path == "/cancel":
            stopped = self.service.cancel()
            self._send_json({"action": "stopped" if stopped else "noop"})
        else:
            self._send_json({"error": "not found"}, status=404)


def serve(settings: Settings | None = None) -> int:
    settings = settings or load_settings()
    service = TTSService(settings)
    _Handler.service = service

    server = ThreadingHTTPServer(
        (settings.daemon_host, settings.daemon_port), _Handler
    )

    def _shutdown(*_args: object) -> None:
        # ``server.shutdown()`` blocks until ``serve_forever`` returns, but the
        # signal handler IS running on the main thread that owns
        # ``serve_forever`` — calling shutdown here would deadlock. Dispatch
        # it to a helper thread instead.
        log.info("shutting down")
        service.cancel()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info(
        "tts-cmd daemon listening on http://%s:%d",
        settings.daemon_host,
        settings.daemon_port,
    )
    print(
        f"tts-cmd daemon listening on http://{settings.daemon_host}:{settings.daemon_port}",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0
