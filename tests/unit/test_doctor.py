from __future__ import annotations

import json
from pathlib import Path

import pytest

from readset.cli import main
from readset.ledger import Ledger


def test_should_report_all_checks_when_repo_healthy(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    main(["init"])
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "python" in out and "ok" in out
    assert "ledger" in out
    assert "hooks (claude)" in out
    assert "errors.log" in out
    assert "all checks passed" in out


def test_should_fail_when_not_initialised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "not initialised" in out


def test_should_flag_missing_hooks_and_show_error_tail(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "isolated-home"))
    monkeypatch.chdir(repo)
    ledger = Ledger.open(repo)
    (ledger.dir / "errors.log").write_text("Traceback\nValueError: boom\n")
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "no readset hooks" in out
    assert "ValueError: boom" in out


def test_should_flag_corrupt_ledger(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    main(["init"])
    (repo / ".readset" / "ledger.db").write_bytes(b"garbage")
    assert main(["doctor"]) == 1
    assert "ledger" in capsys.readouterr().out


def test_should_detect_plugin_hooks_when_plugin_installed(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    plugins = home / ".claude" / "plugins" / "installed_plugins.json"
    plugins.parent.mkdir(parents=True)
    plugins.write_text(json.dumps({"plugins": {"readset@readset": [{"scope": "user"}]}}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(repo)
    Ledger.open(repo)
    assert main(["doctor"]) == 0
    assert "plugin" in capsys.readouterr().out
