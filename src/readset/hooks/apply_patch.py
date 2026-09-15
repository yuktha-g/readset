"""Parser for the `apply_patch` format used by Codex.

The format:

    *** Begin Patch
    *** Add File: path
    +line
    *** Update File: path
    *** Move to: newpath          (optional)
    @@ optional context header
     context line
    -removed line
    +added line
    *** Delete File: path
    *** End Patch

Each Update hunk becomes one (old, new) replacement: `old` is the context and removed
lines, `new` is the context and added lines. A hunk with no old lines cannot be located
in the file, so the update carries `edits=None` and is validated as a whole-file write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Op = Literal["add", "update", "delete"]


@dataclass(frozen=True)
class PatchFile:
    """One file touched by a patch."""

    op: Op
    path: str
    edits: list[tuple[str, str]] | None = None
    move_to: str | None = None


def parse_patch(text: str) -> list[PatchFile]:
    """Parse patch text into the files it touches. Non-patch text yields an empty list."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "*** Begin Patch":
        return []
    files: list[PatchFile] = []
    op: Op | None = None
    path = ""
    move_to: str | None = None
    hunks: list[list[str]] = []

    def flush() -> None:
        nonlocal op, path, move_to, hunks
        if op is None:
            return
        edits: list[tuple[str, str]] | None = None
        if op == "update":
            pairs = [_hunk_to_edit(h) for h in hunks]
            edits = [p for p in pairs if p is not None]
            if len(edits) != len(pairs) or not edits:
                edits = None
        files.append(PatchFile(op=op, path=path, edits=edits, move_to=move_to))
        op, path, move_to, hunks = None, "", None, []

    for line in lines[1:]:
        if line.startswith("*** Add File: "):
            flush()
            op, path = "add", line[len("*** Add File: ") :].strip()
            hunks = [[]]
        elif line.startswith("*** Update File: "):
            flush()
            op, path = "update", line[len("*** Update File: ") :].strip()
            hunks = []
        elif line.startswith("*** Delete File: "):
            flush()
            op, path = "delete", line[len("*** Delete File: ") :].strip()
        elif line.startswith("*** Move to: "):
            move_to = line[len("*** Move to: ") :].strip()
        elif line.strip() in ("*** End Patch", "*** End of File"):
            continue
        elif line.startswith("@@"):
            hunks.append([])
        elif op is not None:
            if not hunks:
                hunks.append([])
            hunks[-1].append(line)
    flush()
    return files


def _hunk_to_edit(hunk: list[str]) -> tuple[str, str] | None:
    old: list[str] = []
    new: list[str] = []
    for line in hunk:
        if line.startswith("-"):
            old.append(line[1:])
        elif line.startswith("+"):
            new.append(line[1:])
        else:
            body = line[1:] if line.startswith(" ") else line
            old.append(body)
            new.append(body)
    if not old:
        return None
    return "".join(f"{x}\n" for x in old), "".join(f"{x}\n" for x in new)
