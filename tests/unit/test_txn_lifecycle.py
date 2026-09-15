from __future__ import annotations

from pathlib import Path

from readset.ledger import Ledger
from readset.txn import Ok


def _write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).write_text(text)


def test_should_fold_child_writes_into_parent_when_subagent_ends(repo: Path) -> None:
    _write(repo, "a.py", "v1\n")
    ledger = Ledger.open(repo)
    parent = ledger.begin("session", kind="session")
    parent.record_read("a.py")
    child = ledger.begin("agent-1", kind="agent", parent="session", agent_type="Plan")
    child.record_read("a.py")
    _write(repo, "a.py", "v2\n")
    child.record_write("a.py")
    child.end()
    assert isinstance(parent.validate_write("a.py"), Ok)
    info = ledger.get("agent-1")
    assert info is not None and info.ended_at is not None


def test_should_not_fold_when_transaction_has_no_parent(repo: Path) -> None:
    _write(repo, "a.py", "v1\n")
    ledger = Ledger.open(repo)
    other = ledger.begin("other", kind="session")
    other.record_read("a.py")
    solo = ledger.begin("solo", kind="session")
    solo.record_read("a.py")
    _write(repo, "a.py", "v2\n")
    solo.record_write("a.py")
    solo.end()
    assert not isinstance(other.validate_write("a.py"), Ok)


def test_should_be_noop_when_ending_unknown_transaction(repo: Path) -> None:
    from readset.txn import Transaction

    Transaction(Ledger.open(repo), "ghost").end()


def test_should_refresh_only_mentioned_paths_when_bash_ran(repo: Path) -> None:
    _write(repo, "a.py", "v1\n")
    _write(repo, "b.py", "v1\n")
    t = Ledger.open(repo).begin("t")
    t.record_read("a.py")
    t.record_read("b.py")
    _write(repo, "a.py", "v2\n")
    _write(repo, "b.py", "v2\n")
    refreshed = t.refresh_mentioned("sed -i 's/v1/v2/' a.py")
    assert refreshed == ["a.py"]
    assert isinstance(t.validate_write("a.py", scope="target"), Ok)
    assert not isinstance(t.validate_write("b.py", scope="target"), Ok)


def test_should_not_refresh_when_mentioned_file_unchanged(repo: Path) -> None:
    _write(repo, "a.py", "v1\n")
    t = Ledger.open(repo).begin("t")
    t.record_read("a.py")
    assert t.refresh_mentioned("cat a.py") == []


def test_should_not_match_when_path_is_substring_of_other_token(repo: Path) -> None:
    _write(repo, "a.py", "v1\n")
    t = Ledger.open(repo).begin("t")
    t.record_read("a.py")
    _write(repo, "a.py", "v2\n")
    assert t.refresh_mentioned("cat data.py") == []
    assert t.refresh_mentioned("cat a.pyc") == []


def test_should_match_when_full_relative_path_used(repo: Path) -> None:
    (repo / "src").mkdir()
    _write(repo, "src/a.py", "v1\n")
    t = Ledger.open(repo).begin("t")
    t.record_read("src/a.py")
    _write(repo, "src/a.py", "v2\n")
    assert t.refresh_mentioned("python -c x > src/a.py") == ["src/a.py"]


def test_should_end_stale_transactions_and_collect_blobs_when_gc_runs(repo: Path) -> None:
    _write(repo, "a.py", "v1\n")
    ledger = Ledger.open(repo)
    old = ledger.begin("old", kind="session")
    old.record_read("a.py")
    with ledger.connect() as conn:
        conn.execute("update txn set started_at = started_at - 100000 where txn_id = 'old'")
        conn.execute("update read_set set seen_at = seen_at - 100000 where txn_id = 'old'")
    fresh = ledger.begin("fresh", kind="session")
    _write(repo, "a.py", "v2\n")
    fresh.record_read("a.py")
    report = ledger.gc(older_than_seconds=86400)
    assert report.ended == ["old"]
    assert report.blobs_removed == 1
    info = ledger.get("old")
    assert info is not None and info.ended_at is not None
    assert len(list(ledger.objects_dir.iterdir())) == 1


def test_should_keep_recently_active_transaction_when_gc_runs(repo: Path) -> None:
    _write(repo, "a.py", "v1\n")
    ledger = Ledger.open(repo)
    t = ledger.begin("active", kind="session")
    with ledger.connect() as conn:
        conn.execute("update txn set started_at = started_at - 100000 where txn_id = 'active'")
    t.record_read("a.py")
    report = ledger.gc(older_than_seconds=86400)
    assert report.ended == []
