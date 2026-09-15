"""Minimal ANSI colour helpers. No third-party dependency, honours NO_COLOR."""

from __future__ import annotations

import os
import sys
from typing import IO

_CODES = {
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
    "bold": "1",
    "dim": "2",
}


def wants_colour(stream: IO[str] | None = None) -> bool:
    """Return True when colour output is appropriate for the stream."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    target = stream if stream is not None else sys.stdout
    isatty = getattr(target, "isatty", None)
    return bool(isatty and isatty())


def paint(text: str, colour: str, *, stream: IO[str] | None = None) -> str:
    """Wrap text in an ANSI colour code when the stream supports it."""
    if not wants_colour(stream):
        return text
    code = _CODES[colour]
    return f"\x1b[{code}m{text}\x1b[0m"
