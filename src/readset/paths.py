"""Repository root discovery and path normalisation."""

from __future__ import annotations

import fnmatch
from collections.abc import Sequence
from pathlib import Path

from readset.errors import NotInRepoError, OutsideRepoError

LEDGER_DIR = ".readset"
DEFAULT_IGNORE: tuple[str, ...] = (".readset/**", ".git/**")


def find_repo_root(start: Path) -> Path:
    """Walk upwards from start to the nearest directory holding .readset/ or .git/.

    A .readset/ directory wins over .git/ at the same level or below, so a ledger
    initialised in a sub-package scopes to that package.
    """
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / LEDGER_DIR).is_dir():
            return candidate
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise NotInRepoError(str(start))


def find_ledger_root(start: Path) -> Path | None:
    """Return the nearest ancestor holding .readset/, or None if readset is not initialised."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / LEDGER_DIR).is_dir():
            return candidate
    return None


def relative_path(root: Path, path: str | Path) -> str:
    """Normalise path to a POSIX string relative to root.

    Raises OutsideRepoError if the resolved path is not under root.
    """
    root = root.resolve()
    candidate = Path(path)
    absolute = candidate if candidate.is_absolute() else root / candidate
    try:
        rel = absolute.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise OutsideRepoError(str(path), str(root)) from exc
    return rel.as_posix()


def is_ignored(rel: str, patterns: Sequence[str]) -> bool:
    """Return True if a relative POSIX path matches any ignore pattern.

    A pattern ending in '/**' matches everything under that directory. Other patterns
    are fnmatch globs applied to the full path and to the file name.
    """
    name = rel.rsplit("/", 1)[-1]
    for pattern in patterns:
        if pattern.endswith("/**"):
            prefix = pattern[:-2]
            if rel.startswith(prefix):
                return True
        elif fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern):
            return True
    return False
