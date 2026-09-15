from __future__ import annotations

import io

import pytest

from readset.demo import run


def test_should_show_block_then_success_when_demo_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    out = io.StringIO()
    assert run(out) == 0
    text = out.getvalue()
    assert "blocked" in text
    assert "-TAX_RATE = 0.18" in text and "+TAX_RATE = 0.20" in text
    assert "Changed by: agent-b (Fix)" in text
    assert "write succeeded" in text
    assert "billing.py" in text
