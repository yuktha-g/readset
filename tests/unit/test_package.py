from __future__ import annotations

import pytest

import readset
from readset._term import paint


def test_should_expose_version_when_imported() -> None:
    assert readset.__version__ == "0.2.0"


def test_should_not_colour_when_no_color_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    assert paint("x", "red") == "x"


def test_should_colour_when_force_color_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert paint("x", "red") == "\x1b[31mx\x1b[0m"
