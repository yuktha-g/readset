from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fresh directory that looks like a git repository."""
    (tmp_path / ".git").mkdir()
    return tmp_path
