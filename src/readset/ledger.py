"""The ledger: a SQLite database plus a content-addressed blob store under <repo>/.readset/.

Every hook invocation opens its own short-lived connection. WAL mode and a busy timeout
make concurrent writers from parallel agents safe.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from readset.hashing import hash_bytes
from readset.paths import LEDGER_DIR

if TYPE_CHECKING:
    from readset.txn import Transaction

SCHEMA = """
create table if not exists txn (
  txn_id      text primary key,
  kind        text not null,
  parent_txn  text,
  agent_type  text,
  started_at  real not null,
  ended_at    real
);
create table if not exists read_set (
  txn_id  text not null,
  path    text not null,
  hash    text not null,
  seen_at real not null,
  primary key (txn_id, path)
);
create table if not exists write_log (
  id          integer primary key,
  txn_id      text not null,
  path        text not null,
  old_hash    text,
  new_hash    text not null,
  tool_use_id text,
  written_at  real not null
);
create index if not exists write_log_path_hash on write_log (path, new_hash);
create table if not exists conflict_log (
  id            integer primary key,
  txn_id        text not null,
  path          text not null,
  kind          text not null,
  expected_hash text not null,
  actual_hash   text not null,
  changed_by    text,
  diff          text not null,
  tool_use_id   text,
  detected_at   real not null
);
"""

BUSY_TIMEOUT_MS = 2000


@dataclass(frozen=True)
class TxnInfo:
    """A row of the txn table."""

    txn_id: str
    kind: str
    parent_txn: str | None
    agent_type: str | None
    started_at: float
    ended_at: float | None


@dataclass(frozen=True)
class GcReport:
    """What a gc pass did."""

    ended: list[str]
    blobs_removed: int


class Ledger:
    """Owns the .readset/ directory: the SQLite database and the blob store."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.dir = self.root / LEDGER_DIR
        self.db_path = self.dir / "ledger.db"
        self.objects_dir = self.dir / "objects"

    @classmethod
    def open(cls, root: Path | str) -> Ledger:
        """Create .readset/ and the schema if missing, then return a Ledger."""
        ledger = cls(Path(root))
        ledger.objects_dir.mkdir(parents=True, exist_ok=True)
        conn = ledger.connect()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()
        return ledger

    def connect(self) -> sqlite3.Connection:
        """Open a connection in WAL mode with a busy timeout. The caller closes it.

        Used as `with ledger.connect() as conn:` the block commits on success. Note that
        sqlite3's context manager commits but does not close; short-lived processes make
        that acceptable, and long-lived callers should close explicitly.
        """
        conn = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma journal_mode = wal")
        conn.execute(f"pragma busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.isolation_level = "DEFERRED"
        return conn

    @staticmethod
    def now() -> float:
        """Current time as a POSIX timestamp. Indirected so tests can patch it."""
        return time.time()

    # -- blobs ---------------------------------------------------------------------------

    def store_blob(self, data: bytes) -> str:
        """Write data to the blob store, keyed by its digest, and return the digest."""
        digest = hash_bytes(data)
        target = self.objects_dir / digest
        if not target.exists():
            tmp = target.with_name(f"{digest}.tmp")
            tmp.write_bytes(data)
            tmp.replace(target)
        return digest

    def load_blob(self, digest: str) -> bytes | None:
        """Return the bytes for a digest, or None if the blob is not stored."""
        try:
            return (self.objects_dir / digest).read_bytes()
        except FileNotFoundError:
            return None

    # -- transactions --------------------------------------------------------------------

    def ensure(
        self,
        txn_id: str,
        *,
        kind: str,
        parent: str | None = None,
        agent_type: str | None = None,
    ) -> TxnInfo:
        """Register a transaction if it does not exist and return its row."""
        with self.connect() as conn:
            conn.execute(
                "insert or ignore into txn (txn_id, kind, parent_txn, agent_type, started_at)"
                " values (?, ?, ?, ?, ?)",
                (txn_id, kind, parent, agent_type, self.now()),
            )
        info = self.get(txn_id)
        if info is None:  # pragma: no cover - just inserted
            raise RuntimeError(f"transaction {txn_id!r} vanished after insert")
        return info

    def begin(
        self,
        txn_id: str,
        *,
        kind: str = "library",
        parent: str | None = None,
        agent_type: str | None = None,
    ) -> Transaction:
        """Register the transaction if needed and return a Transaction handle."""
        from readset.txn import Transaction  # local import: txn imports ledger

        self.ensure(txn_id, kind=kind, parent=parent, agent_type=agent_type)
        return Transaction(self, txn_id)

    def get(self, txn_id: str) -> TxnInfo | None:
        """Return the transaction row, or None if unknown."""
        with self.connect() as conn:
            row = conn.execute("select * from txn where txn_id = ?", (txn_id,)).fetchone()
        return _to_info(row) if row is not None else None

    def live_transactions(self) -> list[TxnInfo]:
        """Return transactions that have not ended, oldest first."""
        with self.connect() as conn:
            rows = conn.execute(
                "select * from txn where ended_at is null order by started_at, txn_id"
            ).fetchall()
        return [_to_info(r) for r in rows]

    def gc(self, *, older_than_seconds: float) -> GcReport:
        """End transactions idle for longer than the threshold and drop unreferenced blobs.

        Idle time is measured from the latest of started_at and any read_set seen_at.
        Read sets of ended transactions are deleted so their blobs become collectable;
        write_log and conflict_log are kept as history.
        """
        cutoff = self.now() - older_than_seconds
        with self.connect() as conn:
            rows = conn.execute(
                "select t.txn_id from txn t where t.ended_at is null and"
                " coalesce((select max(seen_at) from read_set r where r.txn_id = t.txn_id),"
                " t.started_at) < ?",
                (cutoff,),
            ).fetchall()
            ended = [r["txn_id"] for r in rows]
            for txn_id in ended:
                conn.execute("update txn set ended_at = ? where txn_id = ?", (self.now(), txn_id))
            conn.execute(
                "delete from read_set where txn_id in"
                " (select txn_id from txn where ended_at is not null)"
            )
            live = {
                r["hash"]
                for r in conn.execute(
                    "select distinct r.hash from read_set r join txn t on t.txn_id = r.txn_id"
                    " where t.ended_at is null"
                ).fetchall()
            }
        removed = 0
        for blob in self.objects_dir.iterdir():
            if blob.name not in live and not blob.name.endswith(".tmp"):
                blob.unlink()
                removed += 1
        return GcReport(ended=ended, blobs_removed=removed)


def _to_info(row: sqlite3.Row) -> TxnInfo:
    return TxnInfo(
        txn_id=row["txn_id"],
        kind=row["kind"],
        parent_txn=row["parent_txn"],
        agent_type=row["agent_type"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
    )
