"""Worktree merge validation: `readset merge-check`.

A branch created from `base` observed every file at `base`; that is a read set. Before
merging into another branch, compare what this checkout changed and read against what the
target branch changed since `base`, with the same hunk-level rules used for live edits.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from readset.diff import unified
from readset.errors import ReadsetError
from readset.hunks import Range, changed_ranges, overlaps
from readset.ledger import Ledger
from readset.paths import find_ledger_root

FindingKind = Literal["overlap", "both_changed", "stale_dependency"]


class GitError(ReadsetError):
    """A git invocation failed or the directory is not a repository."""


@dataclass(frozen=True)
class Finding:
    """One path where the target branch's changes matter to this checkout."""

    path: str
    kind: FindingKind
    ours: list[Range] = field(default_factory=list)
    theirs: list[Range] = field(default_factory=list)
    diff: str = ""
    blocking: bool = False


@dataclass(frozen=True)
class MergeReport:
    """Result of merge_check. `ok` is False when any finding blocks."""

    into: str
    base: str
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        return not any(f.blocking for f in self.findings)


def merge_check(
    root: Path | str,
    *,
    into: str = "main",
    margin: int = 3,
    strict: bool = False,
    diff_max_lines: int = 200,
) -> MergeReport:
    """Validate this checkout's changes and reads against `into` since their merge base.

    Overlapping edits (within `margin` lines) always block. Files this checkout read but did
    not change, which `into` changed, are reported and block only with `strict`.
    """
    root = Path(root).resolve()
    if not (root / ".git").exists():
        raise GitError(f"{root} is not a git repository")
    base = _git(root, "merge-base", "HEAD", into)
    live = _merge_in_progress(root)
    if live:
        # A merge is already applying `into` into the working tree and index (this is the
        # pre-merge-commit hook case): the working tree now mixes both sides, so it cannot
        # be trusted as "ours". Use the committed HEAD instead, which the merge has not
        # touched yet.
        ours = set(_git(root, "diff", "--name-only", base, "HEAD").splitlines())
    else:
        ours = set(_git(root, "diff", "--name-only", base).splitlines())
    theirs = set(_git(root, "diff", "--name-only", base, into).splitlines())
    observed = _observed_paths(root)

    findings: list[Finding] = []
    for path in sorted(theirs):
        if path in ours:
            base_text = _show(root, base, path)
            their_text = _show(root, into, path)
            our_text = _show(root, "HEAD", path) if live else _read_working(root, path)
            our_ranges = changed_ranges(base_text, our_text)
            their_ranges = changed_ranges(base_text, their_text)
            clash = any(overlaps(t, o, margin=margin) for t in their_ranges for o in our_ranges)
            findings.append(
                Finding(
                    path=path,
                    kind="overlap" if clash else "both_changed",
                    ours=our_ranges,
                    theirs=their_ranges,
                    diff=_diff(path, base_text, their_text, into, diff_max_lines),
                    blocking=clash,
                )
            )
        elif path in observed:
            base_text = _show(root, base, path)
            their_text = _show(root, into, path)
            findings.append(
                Finding(
                    path=path,
                    kind="stale_dependency",
                    theirs=changed_ranges(base_text, their_text),
                    diff=_diff(path, base_text, their_text, into, diff_max_lines),
                    blocking=strict,
                )
            )
    return MergeReport(into=into, base=base, findings=findings)


def _merge_in_progress(root: Path) -> bool:
    """True if this checkout is in the middle of a `git merge` (MERGE_HEAD exists)."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "-q", "MERGE_HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def default_target(root: Path) -> str:
    """The branch merges usually go into: origin/HEAD's target, else `main`."""
    try:
        ref = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    except GitError:
        return "main"
    return ref.split("/", 1)[1] if "/" in ref else ref


def _observed_paths(root: Path) -> set[str]:
    ledger_root = find_ledger_root(root)
    if ledger_root is None or ledger_root != root:
        return set()
    ledger = Ledger.open(ledger_root)
    with ledger.connect() as conn:
        reads = {r[0] for r in conn.execute("select distinct path from read_set")}
        writes = {r[0] for r in conn.execute("select distinct path from write_log")}
    return reads | writes


def _git(root: Path, *args: str, raw: bool = False) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {result.stderr.strip() or result.returncode}")
    return result.stdout if raw else result.stdout.strip("\n")


def _show(root: Path, rev: str, path: str) -> str:
    """File content at a revision, byte-faithful; empty if the path does not exist there."""
    try:
        return _git(root, "show", f"{rev}:{path}", raw=True)
    except GitError:
        return ""


def _read_working(root: Path, path: str) -> str:
    try:
        return (root / path).read_text(errors="replace")
    except OSError:
        return ""


def _diff(path: str, base_text: str, their_text: str, into: str, max_lines: int) -> str:
    return unified(
        base_text.encode(),
        their_text.encode(),
        path,
        old_label="merge base",
        new_label=into,
        max_lines=max_lines,
    )
