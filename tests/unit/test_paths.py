from __future__ import annotations

from pathlib import Path

import pytest

from readset.errors import NotInRepoError, OutsideRepoError
from readset.paths import find_ledger_root, find_repo_root, is_ignored, relative_path


def test_should_find_git_root_when_started_in_subdirectory(repo: Path) -> None:
    sub = repo / "a" / "b"
    sub.mkdir(parents=True)
    assert find_repo_root(sub) == repo


def test_should_prefer_readset_dir_when_both_exist(repo: Path) -> None:
    inner = repo / "pkg"
    (inner / ".readset").mkdir(parents=True)
    assert find_repo_root(inner / "x") == inner


def test_should_raise_when_no_root_exists(tmp_path: Path) -> None:
    with pytest.raises(NotInRepoError):
        find_repo_root(tmp_path)


def test_should_return_none_when_ledger_dir_missing(repo: Path) -> None:
    assert find_ledger_root(repo) is None


def test_should_return_root_when_ledger_dir_exists(repo: Path) -> None:
    (repo / ".readset").mkdir()
    assert find_ledger_root(repo / "deep") == repo


def test_should_return_posix_relative_path_when_absolute_inside_root(repo: Path) -> None:
    assert relative_path(repo, repo / "src" / "a.py") == "src/a.py"


def test_should_accept_relative_path_when_given(repo: Path) -> None:
    assert relative_path(repo, "src/../src/a.py") == "src/a.py"


def test_should_raise_when_path_escapes_root(repo: Path) -> None:
    with pytest.raises(OutsideRepoError):
        relative_path(repo, repo.parent / "other.py")


def test_should_ignore_when_pattern_matches_prefix() -> None:
    assert is_ignored(".readset/ledger.db", [".readset/**"])
    assert is_ignored(".git/HEAD", [".git/**"])
    assert not is_ignored("src/a.py", [".git/**", ".readset/**"])


def test_should_ignore_when_glob_matches_name() -> None:
    assert is_ignored("build/out.o", ["*.o"])
