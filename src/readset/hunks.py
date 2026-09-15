"""Line-range arithmetic for hunk-level validation.

All ranges are 1-based, inclusive (start, end) line numbers in the *old* text. A pure
insertion between lines is reported as a point range at the line it precedes.
"""

from __future__ import annotations

from collections.abc import Sequence
from difflib import SequenceMatcher

Range = tuple[int, int]


def changed_ranges(old: str, new: str) -> list[Range]:
    """Return the line ranges of `old` that differ from `new`."""
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    matcher = SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    ranges: list[Range] = []
    for tag, i1, i2, _j1, _j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        start = i1 + 1
        end = max(start, i2)
        ranges.append((start, end))
    return ranges


def locate(text: str, needle: str) -> Range | None:
    """Line range of the single occurrence of `needle` in `text`, or None if not exactly one."""
    if not needle or text.count(needle) != 1:
        return None
    index = text.index(needle)
    start = text.count("\n", 0, index) + 1
    end = start + needle.rstrip("\n").count("\n")
    return start, end


def overlaps(a: Range, b: Range, *, margin: int) -> bool:
    """True if the two ranges intersect once `b` is widened by `margin` lines on each side."""
    return a[0] <= b[1] + margin and a[1] >= b[0] - margin


def apply_edits(text: str, edits: Sequence[tuple[str, str]]) -> str | None:
    """Apply (old, new) replacements in order. Returns None if any old string is not unique."""
    for old, new in edits:
        if not old or text.count(old) != 1:
            return None
        text = text.replace(old, new, 1)
    return text
