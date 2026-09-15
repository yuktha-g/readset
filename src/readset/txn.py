"""The primitive: a transaction's read set, and validation of writes against it."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from readset.diff import render_message, render_notice, unified
from readset.hashing import ABSENT, hash_bytes, read_and_hash
from readset.hunks import apply_edits, changed_ranges, locate, overlaps
from readset.ledger import Ledger

Scope = Literal["strict", "hunk", "target"]
ConflictKind = Literal["stale_read", "blind_overwrite", "stale_dependency"]
Edit = tuple[str, str]


@dataclass(frozen=True)
class Ok:
    """A write is safe to perform. `notice` is optional context for the agent."""

    ok: bool = True
    notice: str = ""


@dataclass(frozen=True)
class Conflict:
    """A write must not be performed. `message` is what the agent should be told."""

    path: str
    kind: ConflictKind
    expected_hash: str
    actual_hash: str
    diff: str
    changed_by: str | None = None
    changed_by_type: str | None = None
    stale_paths: list[str] = field(default_factory=list)
    region_conflict: bool = False
    message: str = ""

    @property
    def ok(self) -> bool:
        return False


Result = Ok | Conflict


class Transaction:
    """One agent's view of the repository. Created via Ledger.begin().

    The read set records, per path, the hash of this transaction's *view* of the file:
    what it read, plus its own edits. The difference between the view and disk is
    therefore always exactly what other transactions changed.
    """

    def __init__(self, ledger: Ledger, txn_id: str) -> None:
        self.ledger = ledger
        self.txn_id = txn_id

    # -- reads ---------------------------------------------------------------------------

    def record_read(self, path: str) -> str:
        """Record that this transaction observed `path` at its current content.

        Returns the content hash, or ABSENT if the file does not exist.
        """
        digest, data = read_and_hash(self.ledger.root / path)
        if data is not None:
            self.ledger.store_blob(data)
        self._upsert_read(path, digest)
        return digest

    def read_set(self) -> dict[str, str]:
        """Return {path: hash} for everything this transaction has observed."""
        with self.ledger.connect() as conn:
            rows = conn.execute(
                "select path, hash from read_set where txn_id = ? order by path", (self.txn_id,)
            ).fetchall()
        return {r["path"]: r["hash"] for r in rows}

    # -- writes --------------------------------------------------------------------------

    def validate_write(
        self,
        path: str,
        *,
        scope: Scope = "hunk",
        edits: Sequence[Edit] | None = None,
        replace_all: bool = False,
        hunk_margin: int = 3,
        tool_use_id: str | None = None,
        diff_max_lines: int = 200,
    ) -> Result:
        """Decide whether this transaction may write `path` now.

        Rules: a blind overwrite of an existing file that was never read is blocked;
        creating an absent file that was never read is allowed; a read whose hash still
        matches disk is allowed; a stale read is blocked with a diff.

        Scopes:
        - `strict`: any stale entry in the read set blocks the write.
        - `hunk`: for string-replacement `edits`, the write is allowed when every edited
          region lies more than `hunk_margin` lines from every change others made; stale
          content elsewhere is reported in `Ok.notice` instead of blocking. Full-file
          writes (no `edits`) and `replace_all` edits still require a fresh read.
        - `target`: only the written file is checked, as a whole.

        A blocked write is recorded in conflict_log.
        """
        entries = self.read_set()
        actual, actual_data = read_and_hash(self.ledger.root / path)
        expected = entries.get(path)
        conflict: Conflict | None = None
        notices: list[str] = []

        if expected is None:
            if actual != ABSENT:
                conflict = Conflict(
                    path=path,
                    kind="blind_overwrite",
                    expected_hash=ABSENT,
                    actual_hash=actual,
                    diff="",
                    changed_by=self._attribute(path, actual),
                )
        elif expected != actual:
            diff = self._diff(path, expected, actual_data, diff_max_lines)
            changed_by = self._attribute(path, actual)
            region_ok = (
                scope == "hunk"
                and edits is not None
                and not replace_all
                and self._edits_clear_of_changes(expected, actual_data, edits, hunk_margin)
            )
            if region_ok:
                notices.append(render_notice(path, diff, changed_by, self._agent_type(changed_by)))
            else:
                conflict = Conflict(
                    path=path,
                    kind="stale_read",
                    expected_hash=expected,
                    actual_hash=actual,
                    diff=diff,
                    changed_by=changed_by,
                    region_conflict=scope == "hunk" and edits is not None and not replace_all,
                )

        stale = self._stale_siblings(entries, exclude=path) if scope != "target" else []

        if scope == "strict" and stale:
            if conflict is None:
                first = stale[0]
                first_actual, first_data = read_and_hash(self.ledger.root / first)
                conflict = Conflict(
                    path=path,
                    kind="stale_dependency",
                    expected_hash=entries[first],
                    actual_hash=first_actual,
                    diff=self._diff(first, entries[first], first_data, diff_max_lines),
                    changed_by=self._attribute(first, first_actual),
                    stale_paths=stale,
                )
            else:
                conflict = dataclasses.replace(conflict, stale_paths=stale)
        elif scope == "hunk" and stale and conflict is None:
            notices.append(render_notice_siblings(stale, self._attributions(stale)))

        if conflict is None:
            return Ok(notice="\n\n".join(notices))
        conflict = self._with_attribution_type(conflict)
        conflict = dataclasses.replace(conflict, message=render_message(conflict))
        self._log_conflict(conflict, tool_use_id)
        return conflict

    def record_write(
        self,
        path: str,
        *,
        edits: Sequence[Edit] | None = None,
        tool_use_id: str | None = None,
    ) -> str:
        """Record that this transaction wrote `path`.

        With `edits`, the transaction's view becomes its previous view with those edits
        applied, so changes by others that it has not read stay invisible to it and keep
        being validated. Without `edits` (a full-file write) the view becomes the disk
        content. Returns the new view hash, or ABSENT if the file was deleted.
        """
        old = self.read_set().get(path)
        digest, data = read_and_hash(self.ledger.root / path)
        if edits is not None and old is not None and old != ABSENT:
            view = self.ledger.load_blob(old)
            if view is not None:
                updated = apply_edits(view.decode("utf-8", errors="replace"), edits)
                if updated is not None:
                    data = updated.encode("utf-8")
                    digest = hash_bytes(data)
        if data is not None:
            self.ledger.store_blob(data)
        with self.ledger.connect() as conn:
            conn.execute(
                "insert into write_log (txn_id, path, old_hash, new_hash, tool_use_id, written_at)"
                " values (?, ?, ?, ?, ?, ?)",
                (self.txn_id, path, old, digest, tool_use_id, self.ledger.now()),
            )
        self._upsert_read(path, digest)
        return digest

    def refresh_mentioned(self, command: str) -> list[str]:
        """Bash heuristic: treat read-set paths named in `command` as this txn's own writes.

        Only paths whose content actually changed are refreshed. Returns those paths.
        """
        refreshed: list[str] = []
        for path, recorded in self.read_set().items():
            if not _mentions(command, path):
                continue
            actual, _ = read_and_hash(self.ledger.root / path)
            if actual != recorded:
                self.record_write(path)
                refreshed.append(path)
        return refreshed

    def end(self) -> None:
        """Close the transaction.

        A subagent's final writes are folded into its parent's read set, so the parent
        sees its child's results without a spurious conflict.
        """
        info = self.ledger.get(self.txn_id)
        if info is None:
            return
        with self.ledger.connect() as conn:
            if info.parent_txn is not None:
                rows = conn.execute(
                    "select path, new_hash from write_log where txn_id = ? order by id",
                    (self.txn_id,),
                ).fetchall()
                final = {r["path"]: r["new_hash"] for r in rows}
                for path, digest in final.items():
                    conn.execute(_UPSERT_READ, (info.parent_txn, path, digest, self.ledger.now()))
            conn.execute(
                "update txn set ended_at = ? where txn_id = ? and ended_at is null",
                (self.ledger.now(), self.txn_id),
            )

    # -- internals -----------------------------------------------------------------------

    def _edits_clear_of_changes(
        self, expected: str, actual_data: bytes | None, edits: Sequence[Edit], margin: int
    ) -> bool:
        """True if every edit targets a unique region of the view that no other change touches."""
        if expected == ABSENT or actual_data is None or not edits:
            return False
        view_bytes = self.ledger.load_blob(expected)
        if view_bytes is None or b"\x00" in view_bytes[:8000] or b"\x00" in actual_data[:8000]:
            return False
        view = view_bytes.decode("utf-8", errors="replace")
        disk = actual_data.decode("utf-8", errors="replace")
        changes = changed_ranges(view, disk)
        for old, _new in edits:
            region = locate(view, old)
            if region is None:
                return False
            if any(overlaps(change, region, margin=margin) for change in changes):
                return False
        return True

    def _diff(self, path: str, expected: str, actual_data: bytes | None, max_lines: int) -> str:
        old = self.ledger.load_blob(expected) if expected != ABSENT else None
        return unified(
            old,
            actual_data,
            path,
            old_label="what you read",
            new_label="on disk now",
            max_lines=max_lines,
        )

    def _upsert_read(self, path: str, digest: str) -> None:
        with self.ledger.connect() as conn:
            conn.execute(_UPSERT_READ, (self.txn_id, path, digest, self.ledger.now()))

    def _stale_siblings(self, entries: dict[str, str], *, exclude: str) -> list[str]:
        stale: list[str] = []
        for path, recorded in entries.items():
            if path == exclude:
                continue
            actual, _ = read_and_hash(self.ledger.root / path)
            if actual != recorded:
                stale.append(path)
        return stale

    def _attribute(self, path: str, digest: str) -> str | None:
        """Find the transaction whose write produced `digest` at `path`, excluding ourselves."""
        with self.ledger.connect() as conn:
            row = conn.execute(
                "select txn_id from write_log where path = ? and new_hash = ? and txn_id != ?"
                " order by id desc limit 1",
                (path, digest, self.txn_id),
            ).fetchone()
        return str(row["txn_id"]) if row is not None else None

    def _attributions(self, paths: Sequence[str]) -> list[str | None]:
        out: list[str | None] = []
        for path in paths:
            actual, _ = read_and_hash(self.ledger.root / path)
            out.append(self._attribute(path, actual))
        return out

    def _agent_type(self, txn_id: str | None) -> str | None:
        if txn_id is None:
            return None
        info = self.ledger.get(txn_id)
        return info.agent_type if info is not None else None

    def _with_attribution_type(self, conflict: Conflict) -> Conflict:
        if conflict.changed_by is None:
            return conflict
        return dataclasses.replace(conflict, changed_by_type=self._agent_type(conflict.changed_by))

    def _log_conflict(self, conflict: Conflict, tool_use_id: str | None) -> None:
        with self.ledger.connect() as conn:
            conn.execute(
                "insert into conflict_log (txn_id, path, kind, expected_hash, actual_hash,"
                " changed_by, diff, tool_use_id, detected_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self.txn_id,
                    conflict.path,
                    conflict.kind,
                    conflict.expected_hash,
                    conflict.actual_hash,
                    conflict.changed_by,
                    conflict.diff,
                    tool_use_id,
                    self.ledger.now(),
                ),
            )


def render_notice_siblings(paths: Sequence[str], changed_by: Sequence[str | None]) -> str:
    """Notice text for stale files other than the one being written."""
    items = []
    for path, who in zip(paths, changed_by, strict=True):
        items.append(f"{path} (changed by {who})" if who else path)
    return (
        "readset: heads-up - other files you read have changed since: "
        + ", ".join(items)
        + ". Your write was allowed. Read them again before relying on their contents."
    )


_UPSERT_READ = (
    "insert into read_set (txn_id, path, hash, seen_at) values (?, ?, ?, ?)"
    " on conflict (txn_id, path) do update set hash = excluded.hash, seen_at = excluded.seen_at"
)


def _mentions(command: str, path: str) -> bool:
    """True if `path` (or its basename) appears as a whole token in the command."""
    name = path.rsplit("/", 1)[-1]
    pattern = r"(?<![\w./-])(?:" + re.escape(path) + "|" + re.escape(name) + r")(?![\w-])"
    return re.search(pattern, command) is not None
