"""Content hashing. The ledger stores sha256 digests; ABSENT marks a path with no file."""

from __future__ import annotations

import hashlib
from pathlib import Path

ABSENT = "absent"


def hash_bytes(data: bytes) -> str:
    """Return the sha256 hex digest of data."""
    return hashlib.sha256(data).hexdigest()


def read_and_hash(path: Path) -> tuple[str, bytes | None]:
    """Read a file and return (digest, bytes).

    Missing files, directories and unreadable files yield (ABSENT, None).
    """
    try:
        data = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError, PermissionError, NotADirectoryError):
        return ABSENT, None
    return hash_bytes(data), data
