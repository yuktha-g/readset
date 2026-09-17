from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from readset.git_hook import MARKER, install_git_hook, uninstall_git_hook

ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "PATH": "/usr/bin:/bin",
}
TEN = "".join(f"line{i}\n" for i in range(1, 11))


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True, env=ENV
    )


@pytest.fixture
def repo_pair(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "f.py").write_text(TEN)
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "base")
    wt = tmp_path / "wt"
    git(main, "worktree", "add", "-q", "-b", "feature", str(wt))
    return main, wt


def test_should_write_executable_hook_when_installed(repo_pair: tuple[Path, Path]) -> None:
    main, wt = repo_pair
    result = install_git_hook(wt, executable="/x/readset")
    # Hooks are shared across worktrees, so this lands in the main repo's common git dir.
    hook = main / ".git" / "hooks" / "prepare-commit-msg"
    assert result.installed
    assert hook.exists()
    assert hook.stat().st_mode & 0o111
    assert MARKER in hook.read_text()
    assert "/x/readset" in hook.read_text()


def test_should_be_idempotent_when_installed_twice(repo_pair: tuple[Path, Path]) -> None:
    _, wt = repo_pair
    install_git_hook(wt, executable="/x/readset")
    second = install_git_hook(wt, executable="/x/readset")
    assert not second.installed
    assert second.reason == "already installed"


def test_should_refuse_to_clobber_foreign_hook(repo_pair: tuple[Path, Path]) -> None:
    main, wt = repo_pair
    hooks_dir = main / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    foreign = hooks_dir / "prepare-commit-msg"
    foreign.write_text("#!/bin/sh\necho mine\n")
    foreign.chmod(0o755)
    result = install_git_hook(wt, executable="/x/readset")
    assert not result.installed
    assert result.reason == "foreign hook present"
    assert foreign.read_text() == "#!/bin/sh\necho mine\n"


def test_should_only_remove_own_hook_when_uninstalling(repo_pair: tuple[Path, Path]) -> None:
    main, wt = repo_pair
    install_git_hook(wt, executable="/x/readset")
    assert uninstall_git_hook(wt) is True
    assert not (main / ".git" / "hooks" / "prepare-commit-msg").exists()
    assert uninstall_git_hook(wt) is False


def test_should_leave_foreign_hook_alone_when_uninstalling(repo_pair: tuple[Path, Path]) -> None:
    main, wt = repo_pair
    hooks_dir = main / ".git" / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    foreign = hooks_dir / "prepare-commit-msg"
    foreign.write_text("#!/bin/sh\necho mine\n")
    assert uninstall_git_hook(wt) is False
    assert foreign.exists()


def test_should_fail_when_not_a_git_repo(tmp_path: Path) -> None:
    result = install_git_hook(tmp_path, executable="/x/readset")
    assert not result.installed
    assert result.reason == "not a git repository"


def test_should_block_merge_when_hunks_overlap(repo_pair: tuple[Path, Path]) -> None:
    # Lines 2 apart: git's own 3-way merge resolves this cleanly with no textual conflict
    # (verified empirically), which is exactly the case readset's hunk_margin exists to catch
    # that git alone would silently let through.
    main, wt = repo_pair
    import sys

    install_git_hook(wt, executable=f"{sys.executable} -m readset.cli")
    (main / "f.py").write_text(TEN.replace("line6\n", "SIX\n"))
    git(main, "commit", "-qam", "main edits 6")
    (wt / "f.py").write_text(TEN.replace("line8\n", "eight\n"))
    git(wt, "commit", "-qam", "feature edits 8")
    clean_merge = git(wt, "merge", "--no-commit", "--no-ff", "main", check=False)
    assert clean_merge.returncode == 0, "test assumption broken: git itself now conflicts here"
    git(wt, "merge", "--abort", check=False)
    result = git(wt, "merge", "main", check=False)
    assert result.returncode != 0
    assert "BLOCK" in result.stdout or "BLOCK" in result.stderr
    assert git(wt, "rev-parse", "--verify", "MERGE_HEAD", check=False).returncode == 0


def test_should_allow_merge_when_changes_are_disjoint(repo_pair: tuple[Path, Path]) -> None:
    main, wt = repo_pair
    import sys

    install_git_hook(wt, executable=f"{sys.executable} -m readset.cli")
    (main / "f.py").write_text(TEN.replace("line1\n", "ONE\n"))
    git(main, "commit", "-qam", "main edits 1")
    (wt / "f.py").write_text(TEN.replace("line9\n", "nine\n"))
    git(wt, "commit", "-qam", "feature edits 9")
    result = git(wt, "merge", "main", check=False)
    assert result.returncode == 0
    assert git(wt, "rev-parse", "--verify", "MERGE_HEAD", check=False).returncode != 0
