"""CLI entry point.

Usage:
    python -m tts_cmd "text to speak"        # one-shot speak (blocking)
    echo "text" | python -m tts_cmd -        # read from stdin
    python -m tts_cmd --serve                # run the HTTP daemon
    python -m tts_cmd --generate-sound       # (re)build the activation cue
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import ACTIVATION_SOUND_PATH, DEACTIVATION_SOUND_PATH
from .daemon import serve
from .service import TTSService
from .sound_effects import generate_activation_sound, generate_deactivation_sound


def _read_text(args: argparse.Namespace) -> str:
    if args.text == ["-"]:
        return sys.stdin.read()
    return " ".join(args.text).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tts_cmd", description="Hotkey-driven TTS daemon/CLI")
    parser.add_argument("text", nargs="*", help="Text to speak (use '-' for stdin)")
    parser.add_argument("--serve", action="store_true", help="Run the HTTP daemon")
    parser.add_argument(
        "--generate-sound",
        action="store_true",
        help="(Re)generate the activation sound WAV and exit",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging (daemon mode)"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    if args.generate_sound:
        for path in (
            generate_activation_sound(ACTIVATION_SOUND_PATH),
            generate_deactivation_sound(DEACTIVATION_SOUND_PATH),
        ):
            print(f"Wrote {path}")
        return 0

    if args.serve:
        return serve()

    text = _read_text(args)
    if not text:
        parser.error("no text supplied (use --serve to run the daemon)")

    return TTSService().speak(text)


if __name__ == "__main__":
    raise SystemExit(main())
