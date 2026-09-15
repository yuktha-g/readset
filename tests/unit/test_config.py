from __future__ import annotations

import json
from pathlib import Path

from readset.config import Config, load, save


def test_should_return_defaults_when_no_config_file(repo: Path) -> None:
    cfg = load(repo)
    assert cfg.scope == "hunk"
    assert cfg.hunk_margin == 3
    assert cfg.diff_max_lines == 200
    assert ".git/**" in cfg.ignore


def test_should_round_trip_when_saved(repo: Path) -> None:
    (repo / ".readset").mkdir()
    save(repo, Config(scope="strict", hunk_margin=0, diff_max_lines=50, ignore=("*.lock",)))
    cfg = load(repo)
    assert cfg == Config(scope="strict", hunk_margin=0, diff_max_lines=50, ignore=("*.lock",))


def test_should_fall_back_to_defaults_when_file_invalid(repo: Path) -> None:
    (repo / ".readset").mkdir()
    (repo / ".readset" / "config.json").write_text("{not json")
    assert load(repo) == Config()


def test_should_fall_back_to_defaults_when_values_invalid(repo: Path) -> None:
    (repo / ".readset").mkdir()
    (repo / ".readset" / "config.json").write_text(
        json.dumps({"scope": "weird", "hunk_margin": -1, "diff_max_lines": -5, "ignore": "nope"})
    )
    assert load(repo) == Config()


def test_should_fall_back_when_top_level_not_object(repo: Path) -> None:
    (repo / ".readset").mkdir()
    (repo / ".readset" / "config.json").write_text("[1, 2]")
    assert load(repo) == Config()


def test_should_ignore_unknown_keys_when_present(repo: Path) -> None:
    (repo / ".readset").mkdir()
    (repo / ".readset" / "config.json").write_text(json.dumps({"scope": "target", "x": 1}))
    assert load(repo).scope == "target"
