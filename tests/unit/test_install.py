from __future__ import annotations

import json
from pathlib import Path

from readset.install import ensure_gitignore, hook_config, install_hooks, remove_hooks


def test_should_cover_required_events_when_config_built() -> None:
    cfg = hook_config("/opt/bin/readset")
    assert set(cfg) == {
        "PreToolUse",
        "PostToolUse",
        "SubagentStart",
        "SubagentStop",
        "SessionStart",
        "SessionEnd",
    }
    pre = cfg["PreToolUse"][0]
    assert pre["matcher"] == "Edit|Write|MultiEdit|NotebookEdit"
    assert pre["hooks"][0]["command"] == "/opt/bin/readset hook"
    assert cfg["PostToolUse"][0]["matcher"] == "Read|Edit|Write|MultiEdit|NotebookEdit|Bash"


def test_should_create_settings_when_missing(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    assert install_hooks(settings, "/x/readset") is True
    data = json.loads(settings.read_text())
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "/x/readset hook"


def test_should_preserve_other_hooks_when_installing(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
    settings.write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"PreToolUse": [other]}})
    )
    install_hooks(settings, "/x/readset")
    data = json.loads(settings.read_text())
    assert data["permissions"] == {"allow": ["Bash(ls)"]}
    commands = [h["command"] for group in data["hooks"]["PreToolUse"] for h in group["hooks"]]
    assert "echo hi" in commands and "/x/readset hook" in commands


def test_should_be_idempotent_when_installed_twice(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    install_hooks(settings, "/x/readset")
    assert install_hooks(settings, "/x/readset") is False
    data = json.loads(settings.read_text())
    assert len(data["hooks"]["PreToolUse"]) == 1


def test_should_replace_stale_path_when_executable_moved(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    install_hooks(settings, "/old/readset")
    assert install_hooks(settings, "/new/readset") is True
    text = settings.read_text()
    assert "/new/readset hook" in text and "/old/readset" not in text


def test_should_remove_only_readset_hooks_when_uninstalling(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    other = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [other]}}))
    install_hooks(settings, "/x/readset")
    assert remove_hooks(settings) is True
    data = json.loads(settings.read_text())
    assert data["hooks"] == {"PreToolUse": [other]}
    assert remove_hooks(settings) is False


def test_should_tolerate_malformed_settings_when_installing(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text("{broken")
    assert install_hooks(settings, "/x/readset") is True
    assert "PreToolUse" in json.loads(settings.read_text())["hooks"]


def test_should_keep_unrecognised_hook_shapes_when_stripping(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"PreToolUse": "weird", "Stop": [{"nohooks": 1}]}}))
    install_hooks(settings, "/x/readset")
    data = json.loads(settings.read_text())
    assert data["hooks"]["Stop"] == [{"nohooks": 1}]
    assert data["hooks"]["PreToolUse"][0] == "weird"


def test_should_append_gitignore_entry_when_missing(repo: Path) -> None:
    (repo / ".gitignore").write_text("*.pyc")
    assert ensure_gitignore(repo) is True
    assert (repo / ".gitignore").read_text() == "*.pyc\n.readset/\n"
    assert ensure_gitignore(repo) is False


def test_should_create_gitignore_when_absent(repo: Path) -> None:
    assert ensure_gitignore(repo) is True
    assert (repo / ".gitignore").read_text() == ".readset/\n"
