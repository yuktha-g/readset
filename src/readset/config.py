"""Per-repository configuration stored at .readset/config.json."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from readset.paths import DEFAULT_IGNORE, LEDGER_DIR

CONFIG_FILE = "config.json"
Scope = Literal["readset", "target"]


@dataclass(frozen=True)
class Config:
    """Validation scope, diff size cap and ignore patterns."""

    scope: Scope = "readset"
    diff_max_lines: int = 200
    ignore: tuple[str, ...] = DEFAULT_IGNORE


def _path(root: Path) -> Path:
    return root / LEDGER_DIR / CONFIG_FILE


def load(root: Path) -> Config:
    """Load config, falling back to defaults for a missing, unreadable or invalid file."""
    try:
        raw = json.loads(_path(root).read_text())
    except (OSError, ValueError):
        return Config()
    if not isinstance(raw, dict):
        return Config()
    scope: Scope = "target" if raw.get("scope") == "target" else "readset"
    diff_max_lines = raw.get("diff_max_lines", 200)
    if not isinstance(diff_max_lines, int) or diff_max_lines < 1:
        diff_max_lines = 200
    ignore = raw.get("ignore", list(DEFAULT_IGNORE))
    if not isinstance(ignore, list) or not all(isinstance(p, str) for p in ignore):
        ignore = list(DEFAULT_IGNORE)
    return Config(scope=scope, diff_max_lines=diff_max_lines, ignore=tuple(ignore))


def save(root: Path, config: Config) -> None:
    """Write config as pretty JSON. Requires .readset/ to exist."""
    data = asdict(config)
    data["ignore"] = list(config.ignore)
    _path(root).write_text(json.dumps(data, indent=2) + "\n")
