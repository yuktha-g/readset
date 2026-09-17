"""Install `merge-check` as a git hook, so it runs itself before a merge commit is made.

Uses `prepare-commit-msg` rather than the more obviously-named `pre-merge-commit`. Both fire
for a merge and both can abort it by exiting non-zero, but `pre-merge-commit` fires too early:
empirically (git 2.40), `MERGE_HEAD` is not yet resolvable at that point, only appearing by
the time `prepare-commit-msg` runs. `prepare-commit-msg` fires for every commit, not only
merges, so the installed hook checks its second argument (`$2`, the message source) and exits
0 immediately unless it is `merge`.

Neither hook fires for a fast-forward merge (no commit is created) or for `git rebase`. By
the time either hook runs, git has already applied the merge to the working tree and index,
which is why `merge_check` reads `HEAD` rather than the working tree when a merge is in
progress - see the note in `merge.py`.
"""

from __future__ import annotations

import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

MARKER = "# installed-by: readset"
HOOK_NAME = "prepare-commit-msg"

_TEMPLATE = """#!/bin/sh
{marker}
# prepare-commit-msg fires for every commit; only act on a merge ($2 = "merge").
[ "$2" = "merge" ] || exit 0
# Runs `readset merge-check` before this merge commit is created. Exits non-zero (and
# aborts the merge, leaving it paused exactly as an ordinary conflict would) when the
# merge-check finds a blocking conflict.
exec {executable} merge-check --into MERGE_HEAD
"""


@dataclass(frozen=True)
class InstallResult:
    """Outcome of install_git_hook."""

    installed: bool
    reason: str = ""


def install_git_hook(root: Path, *, executable: str) -> InstallResult:
    """Write the pre-merge-commit hook. Refuses to overwrite a hook readset did not install.

    Hooks live in the repository's *common* git directory, which is shared across all
    worktrees rather than being per-worktree, so this resolves that path via git itself
    instead of assuming `<root>/.git/hooks`.
    """
    dir_ = hooks_dir(root)
    if dir_ is None:
        return InstallResult(False, "not a git repository")
    path = dir_ / HOOK_NAME
    if path.exists():
        if MARKER not in path.read_text(errors="replace"):
            return InstallResult(False, "foreign hook present")
        if path.read_text() == _TEMPLATE.format(marker=MARKER, executable=executable):
            return InstallResult(False, "already installed")
    dir_.mkdir(parents=True, exist_ok=True)
    path.write_text(_TEMPLATE.format(marker=MARKER, executable=executable))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return InstallResult(True)


def uninstall_git_hook(root: Path) -> bool:
    """Remove the hook if and only if readset installed it. Returns True if removed."""
    dir_ = hooks_dir(root)
    if dir_ is None:
        return False
    path = dir_ / HOOK_NAME
    if not path.exists() or MARKER not in path.read_text(errors="replace"):
        return False
    path.unlink()
    return True


def hooks_dir(root: Path) -> Path | None:
    """The shared hooks directory for the repository root belongs to, or None if not a repo."""
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    common = Path(result.stdout.strip())
    if not common.is_absolute():
        common = (root / common).resolve()
    return common / "hooks"
