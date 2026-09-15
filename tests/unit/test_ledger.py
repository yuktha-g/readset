from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from readset.ledger import Ledger


def test_should_create_ledger_dir_and_schema_when_opened(repo: Path) -> None:
    ledger = Ledger.open(repo)
    assert ledger.db_path.exists()
    assert ledger.objects_dir.is_dir()
    conn = ledger.connect()
    names = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
    conn.close()
    assert {"txn", "read_set", "write_log", "conflict_log"} <= names


def test_should_be_idempotent_when_opened_twice(repo: Path) -> None:
    Ledger.open(repo)
    Ledger.open(repo)
    conn = Ledger.open(repo).connect()
    mode = conn.execute("pragma journal_mode").fetchone()[0]
    conn.close()
    assert mode == "wal"


def test_should_round_trip_blob_when_stored(repo: Path) -> None:
    ledger = Ledger.open(repo)
    digest = ledger.store_blob(b"payload")
    assert ledger.load_blob(digest) == b"payload"
    assert ledger.load_blob("0" * 64) is None


def test_should_register_transaction_once_when_ensured_twice(repo: Path) -> None:
    ledger = Ledger.open(repo)
    first = ledger.ensure("t1", kind="session")
    second = ledger.ensure("t1", kind="agent", parent="other")
    assert first.kind == "session"
    assert second.kind == "session"
    assert second.parent_txn is None


def test_should_list_only_live_transactions_when_some_ended(repo: Path) -> None:
    ledger = Ledger.open(repo)
    ledger.ensure("a", kind="session")
    ledger.ensure("b", kind="agent", parent="a", agent_type="Explore")
    with ledger.connect() as conn:
        conn.execute("update txn set ended_at = ? where txn_id = 'b'", (ledger.now(),))
    live = ledger.live_transactions()
    assert [t.txn_id for t in live] == ["a"]


def test_should_return_none_when_transaction_unknown(repo: Path) -> None:
    assert Ledger.open(repo).get("missing") is None


def test_should_tolerate_concurrent_connections_when_writing(repo: Path) -> None:
    ledger = Ledger.open(repo)
    conns = [ledger.connect() for _ in range(4)]
    for i, conn in enumerate(conns):
        with conn:
            conn.execute(
                "insert into txn (txn_id, kind, started_at) values (?, 'session', ?)",
                (f"t{i}", ledger.now()),
            )
    for conn in conns:
        conn.close()
    assert len(ledger.live_transactions()) == 4


def test_should_expose_sqlite_errors_when_db_corrupt(repo: Path) -> None:
    ledger = Ledger.open(repo)
    ledger.db_path.write_bytes(b"not a database")
    with pytest.raises(sqlite3.DatabaseError):
        Ledger.open(repo).live_transactions()


def test_should_store_same_blob_from_many_processes_without_error(repo: Path) -> None:
    import multiprocessing as mp

    ledger = Ledger.open(repo)
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_store_many, args=(str(repo),)) for _ in range(6)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
    assert all(p.exitcode == 0 for p in procs)
    assert ledger.load_blob(ledger.store_blob(b"shared")) == b"shared"
    assert not [f for f in ledger.objects_dir.iterdir() if f.name.endswith(".tmp")]


def _store_many(root: str) -> None:
    ledger = Ledger.open(root)
    for _ in range(200):
        ledger.store_blob(b"shared")
