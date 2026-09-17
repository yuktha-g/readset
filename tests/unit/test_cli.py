from __future__ import annotations

import json
from pathlib import Path

import pytest

from readset.cli import main, parse_duration
from readset.ledger import Ledger


def test_should_initialise_repo_when_init_runs(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    assert main(["init", "--scope", "strict"]) == 0
    assert (repo / ".readset" / "ledger.db").exists()
    assert json.loads((repo / ".readset" / "config.json").read_text())["scope"] == "strict"
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    assert "PreToolUse" in settings["hooks"]
    command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert command.endswith("readset hook") or command.endswith("readset.cli hook")
    assert ".readset/" in (repo / ".gitignore").read_text()
    assert "readset initialised" in capsys.readouterr().out


def test_should_initialise_in_cwd_when_not_a_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert (tmp_path / ".readset" / "ledger.db").exists()


def test_should_install_user_settings_when_user_flag_given(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(repo)
    assert main(["init", "--user"]) == 0
    assert (home / ".claude" / "settings.json").exists()
    assert main(["uninstall", "--user"]) == 0
    assert json.loads((home / ".claude" / "settings.json").read_text()).get("hooks", {}) == {}


def test_should_remove_hooks_when_uninstall_runs(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    main(["init"])
    assert main(["uninstall"]) == 0
    settings = json.loads((repo / ".claude" / "settings.json").read_text())
    assert settings.get("hooks", {}) == {}
    assert main(["uninstall"]) == 0
    assert "no readset hooks" in capsys.readouterr().out


def test_should_print_live_transactions_when_status_runs(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    ledger = Ledger.open(repo)
    (repo / "a.py").write_text("x")
    ledger.begin("sess-1", kind="session").record_read("a.py")
    ledger.begin("ag-1", kind="agent", parent="sess-1", agent_type="Plan")
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "sess-1" in out and "a.py" in out and "ag-1 (Plan)" in out


def test_should_say_so_when_status_has_no_transactions(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    Ledger.open(repo)
    assert main(["status"]) == 0
    assert "no live transactions" in capsys.readouterr().out


def test_should_print_conflicts_when_log_runs(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    ledger = Ledger.open(repo)
    (repo / "a.py").write_text("v1\n")
    t = ledger.begin("sess-1")
    t.record_read("a.py")
    b = ledger.begin("sess-2")
    b.record_read("a.py")
    (repo / "a.py").write_text("v2\n")
    b.record_write("a.py")
    t.validate_write("a.py")
    assert main(["log"]) == 0
    out = capsys.readouterr().out
    assert "a.py" in out and "stale_read" in out and "changed by sess-2" in out


def test_should_say_so_when_log_is_empty(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    Ledger.open(repo)
    assert main(["log"]) == 0
    assert "no conflicts" in capsys.readouterr().out


def test_should_report_when_gc_runs(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    Ledger.open(repo)
    assert main(["gc", "--older-than", "1h"]) == 0
    assert "ended 0" in capsys.readouterr().out


def test_should_fail_when_gc_duration_invalid(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    Ledger.open(repo)
    assert main(["gc", "--older-than", "soon"]) == 2
    assert "duration" in capsys.readouterr().err


def test_should_fail_when_status_runs_outside_initialised_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["status"]) == 1
    assert main(["log"]) == 1
    assert main(["gc"]) == 1
    assert "readset init" in capsys.readouterr().err


def test_should_print_help_when_no_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage" in capsys.readouterr().out


def test_should_parse_durations_when_given_units() -> None:
    assert parse_duration("90") == 90
    assert parse_duration("2m") == 120
    assert parse_duration("3h") == 10800
    assert parse_duration("1d") == 86400
    with pytest.raises(ValueError, match="duration"):
        parse_duration("soon")


def test_should_install_codex_hooks_when_agent_all(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    assert main(["init", "--agent", "all"]) == 0
    assert (repo / ".codex" / "hooks.json").exists()
    assert (repo / ".claude" / "settings.json").exists()
    out = capsys.readouterr().out
    assert "codex" in out and "claude" in out
    assert main(["uninstall", "--agent", "codex"]) == 0
    assert json.loads((repo / ".codex" / "hooks.json").read_text()).get("hooks", {}) == {}
    assert "PreToolUse" in json.loads((repo / ".claude" / "settings.json").read_text())["hooks"]


def test_should_shorten_uuid_ids_when_displaying() -> None:
    from readset.cli import _short

    assert _short("3ebbb534-35fd-4aaf-aa41-83512a6b6f63") == "3ebbb534"
    assert _short("agent-a") == "agent-a"


def test_should_emit_json_when_log_json_requested(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(repo)
    ledger = Ledger.open(repo)
    (repo / "a.py").write_text("v1\n")
    t = ledger.begin("s")
    t.record_read("a.py")
    (repo / "a.py").write_text("v2\n")
    t.validate_write("a.py")
    assert main(["log", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data[0]["path"] == "a.py" and data[0]["kind"] == "stale_read"


def test_should_install_and_uninstall_git_hook_via_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    monkeypatch.chdir(repo)
    assert main(["install-git-hook"]) == 0
    out = capsys.readouterr().out
    assert "installed" in out
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    assert hook.exists()
    assert main(["install-git-hook"]) == 0
    assert "already installed" in capsys.readouterr().out
    assert main(["uninstall-git-hook"]) == 0
    assert "hook removed" in capsys.readouterr().out
    assert not hook.exists()
    assert main(["uninstall-git-hook"]) == 0
    assert "no readset git hook found" in capsys.readouterr().out


def test_should_report_error_when_git_hook_install_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["install-git-hook"]) == 1
    assert "not installed" in capsys.readouterr().err


def test_should_include_all_subcommands_in_help(capsys: pytest.CaptureFixture[str]) -> None:
    main([])
    out = capsys.readouterr().out
    for command in (
        "init",
        "uninstall",
        "status",
        "log",
        "gc",
        "merge-check",
        "install-git-hook",
        "uninstall-git-hook",
        "doctor",
        "demo",
        "hook",
    ):
        assert command in out, f"{command!r} missing from --help output"
