from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from readset.ledger import Ledger
from readset.merge import GitError, merge_check

TEN = "".join(f"line{i}\n" for i in range(1, 11))
ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={**ENV, "PATH": "/usr/bin:/bin"},
    ).stdout.strip()


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    """A main checkout and a worktree on branch `feature`, both at the same base commit."""
    main = tmp_path / "main"
    main.mkdir()
    git(main, "init", "-q", "-b", "main")
    (main / "f.py").write_text(TEN)
    (main / "g.py").write_text("g1\ng2\ng3\n")
    git(main, "add", "-A")
    git(main, "commit", "-q", "-m", "base")
    wt = tmp_path / "wt"
    git(main, "worktree", "add", "-q", "-b", "feature", str(wt))
    return main, wt


def test_should_report_clean_when_main_unchanged(repos: tuple[Path, Path]) -> None:
    main, wt = repos
    (wt / "f.py").write_text(TEN.replace("line9\n", "nine\n"))
    report = merge_check(wt, into="main")
    assert report.ok
    assert report.findings == []
    assert report.base == git(main, "rev-parse", "HEAD")


def test_should_flag_overlap_when_both_sides_edit_near_same_lines(
    repos: tuple[Path, Path],
) -> None:
    main, wt = repos
    (main / "f.py").write_text(TEN.replace("line8\n", "EIGHT\n"))
    git(main, "commit", "-qam", "main edits 8")
    (wt / "f.py").write_text(TEN.replace("line9\n", "nine\n"))
    report = merge_check(wt, into="main", margin=3)
    assert not report.ok
    finding = report.findings[0]
    assert finding.path == "f.py" and finding.kind == "overlap"
    assert finding.ours == [(9, 9)] and finding.theirs == [(8, 8)]
    assert "-line8" in finding.diff and "+EIGHT" in finding.diff


def test_should_notice_not_fail_when_both_edit_far_apart(repos: tuple[Path, Path]) -> None:
    main, wt = repos
    (main / "f.py").write_text(TEN.replace("line1\n", "ONE\n"))
    git(main, "commit", "-qam", "main edits 1")
    (wt / "f.py").write_text(TEN.replace("line9\n", "nine\n"))
    report = merge_check(wt, into="main", margin=3)
    assert report.ok
    assert report.findings[0].kind == "both_changed"


def test_should_flag_stale_dependency_when_read_file_changed_upstream(
    repos: tuple[Path, Path],
) -> None:
    main, wt = repos
    Ledger.open(wt).begin("agent").record_read("g.py")
    (main / "g.py").write_text("g1\nG2\ng3\n")
    git(main, "commit", "-qam", "main edits g")
    (wt / "f.py").write_text(TEN.replace("line9\n", "nine\n"))
    report = merge_check(wt, into="main")
    assert report.ok
    assert [f.kind for f in report.findings] == ["stale_dependency"]
    strict = merge_check(wt, into="main", strict=True)
    assert not strict.ok


def test_should_ignore_upstream_files_never_read_or_changed(repos: tuple[Path, Path]) -> None:
    main, wt = repos
    (main / "h.py").write_text("new\n")
    git(main, "add", "h.py")
    git(main, "commit", "-qm", "main adds h")
    report = merge_check(wt, into="main")
    assert report.ok and report.findings == []


def test_should_consider_committed_worktree_changes(repos: tuple[Path, Path]) -> None:
    main, wt = repos
    (wt / "f.py").write_text(TEN.replace("line9\n", "nine\n"))
    git(wt, "commit", "-qam", "feature edits 9")
    (main / "f.py").write_text(TEN.replace("line9\n", "NINE\n"))
    git(main, "commit", "-qam", "main edits 9")
    assert not merge_check(wt, into="main").ok


def test_should_raise_when_branch_unknown(repos: tuple[Path, Path]) -> None:
    _, wt = repos
    with pytest.raises(GitError):
        merge_check(wt, into="does-not-exist")


def test_should_raise_when_not_a_git_repo(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        merge_check(tmp_path, into="main")


def test_should_exit_one_and_print_block_when_cli_finds_overlap(
    repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from readset.cli import main

    main_repo, wt = repos
    (main_repo / "f.py").write_text(TEN.replace("line8\n", "EIGHT\n"))
    git(main_repo, "commit", "-qam", "main edits 8")
    (wt / "f.py").write_text(TEN.replace("line9\n", "nine\n"))
    monkeypatch.chdir(wt)
    assert main(["merge-check", "--into", "main"]) == 1
    out = capsys.readouterr().out
    assert "BLOCK" in out and "+EIGHT" in out and "not safe to merge" in out


def test_should_exit_zero_and_emit_json_when_clean(
    repos: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    from readset.cli import main

    _, wt = repos
    monkeypatch.chdir(wt)
    assert main(["merge-check", "--into", "main", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["findings"] == []
    assert main(["merge-check", "--into", "main"]) == 0
    assert "clean" in capsys.readouterr().out


def test_should_exit_two_when_target_missing_or_not_repo(
    repos: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from readset.cli import main

    _, wt = repos
    monkeypatch.chdir(wt)
    assert main(["merge-check", "--into", "nope"]) == 2
    monkeypatch.chdir(tmp_path)
    assert main(["merge-check"]) == 2


def test_should_default_target_to_main_when_no_origin(repos: tuple[Path, Path]) -> None:
    from readset.merge import default_target

    _, wt = repos
    assert default_target(wt) == "main"
