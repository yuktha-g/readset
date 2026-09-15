"""Rendering conflicts for humans and agents: unified diffs and the message an agent sees."""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from readset.txn import Conflict

_BINARY_PROBE = 8000


def _is_binary(data: bytes | None) -> bool:
    return data is not None and b"\x00" in data[:_BINARY_PROBE]


def unified(
    old: bytes | None,
    new: bytes | None,
    path: str,
    *,
    old_label: str,
    new_label: str,
    max_lines: int,
) -> str:
    """Return a unified diff between two file versions, truncated to max_lines.

    None means the file did not exist on that side. Binary content is summarised
    rather than diffed.
    """
    if old is None and new is None:
        return f"{path}: did not exist on either side"
    if old is None:
        size = len(new) if new is not None else 0
        return f"{path}: did not exist when you read it; now exists ({size} bytes)"
    if new is None:
        return f"{path}: existed when you read it ({len(old)} bytes); now deleted"
    if _is_binary(old) or _is_binary(new):
        return f"{path}: binary file changed ({len(old)} -> {len(new)} bytes)"
    old_lines = old.decode("utf-8", errors="replace").splitlines(keepends=True)
    new_lines = new.decode("utf-8", errors="replace").splitlines(keepends=True)
    lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"{path} ({old_label})",
            tofile=f"{path} ({new_label})",
            n=3,
        )
    )
    if len(lines) > max_lines:
        hidden = len(lines) - max_lines
        lines = [*lines[:max_lines], f"... diff truncated, {hidden} more lines\n"]
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def human_age(seconds: float) -> str:
    """Render a duration as '5s ago', '2m ago', '2h ago' or '1d ago'."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def render_message(conflict: Conflict) -> str:
    """Build the text an agent receives when a write is blocked.

    The message leads with what happened, shows who changed it when known, includes
    the diff, and ends with the one action that resolves it: read again, then retry.
    """
    lines: list[str] = []
    if conflict.kind == "blind_overwrite":
        lines.append(
            f"readset: write to {conflict.path} blocked - the file exists and you never read it."
        )
        lines.append("")
        lines.append(
            "Overwriting a file you have not read discards whatever is there, possibly another"
            " agent's work."
        )
    elif conflict.kind == "stale_dependency":
        lines.append(
            f"readset: write to {conflict.path} blocked - files you read and are relying on"
            " have changed."
        )
    elif conflict.region_conflict:
        lines.append(
            f"readset: write to {conflict.path} blocked - the region you are editing changed"
            " after you read it."
        )
    else:
        lines.append(
            f"readset: write to {conflict.path} blocked - the file changed after you read it."
        )
    if conflict.changed_by:
        who = conflict.changed_by
        if conflict.changed_by_type:
            who = f"{who} ({conflict.changed_by_type})"
        lines.append("")
        lines.append(f"Changed by: {who}")
    if conflict.diff:
        lines.append("")
        lines.append(conflict.diff.rstrip("\n"))
    if conflict.stale_paths:
        lines.append("")
        lines.append("Also stale in your read set: " + ", ".join(conflict.stale_paths))
    lines.append("")
    targets = list(dict.fromkeys([conflict.path, *conflict.stale_paths]))
    lines.append(
        "What to do: Read "
        + ", ".join(targets)
        + " again, then retry your edit against the current content."
    )
    return "\n".join(lines)


def render_notice(path: str, diff: str, changed_by: str | None, changed_by_type: str | None) -> str:
    """Notice text when a write is allowed but the file changed outside the edited region."""
    who = ""
    if changed_by:
        who = f" (changed by {changed_by}"
        who += f" ({changed_by_type}))" if changed_by_type else ")"
    body = [
        f"readset: heads-up - {path} changed since you read it{who}, outside the region you"
        " are editing. Your edit was allowed. The changes:",
        "",
        diff.rstrip("\n"),
    ]
    return "\n".join(body)
