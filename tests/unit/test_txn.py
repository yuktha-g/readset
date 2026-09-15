from __future__ import annotations

from pathlib import Path

from readset.hashing import ABSENT
from readset.ledger import Ledger
from readset.txn import Conflict, Ok


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_should_record_hash_when_file_read(repo: Path) -> None:
    _write(repo, "a.py", "one")
    t = Ledger.open(repo).begin("t1")
    digest = t.record_read("a.py")
    assert t.read_set() == {"a.py": digest}
    assert digest != ABSENT


def test_should_record_absent_when_missing_file_read(repo: Path) -> None:
    t = Ledger.open(repo).begin("t1")
    assert t.record_read("ghost.py") == ABSENT


def test_should_allow_write_when_hash_matches_disk(repo: Path) -> None:
    _write(repo, "a.py", "one")
    t = Ledger.open(repo).begin("t1")
    t.record_read("a.py")
    assert isinstance(t.validate_write("a.py", scope="target"), Ok)


def test_should_allow_creation_when_file_absent_and_never_read(repo: Path) -> None:
    t = Ledger.open(repo).begin("t1")
    assert isinstance(t.validate_write("new.py", scope="target"), Ok)


def test_should_allow_creation_when_absent_file_was_read(repo: Path) -> None:
    t = Ledger.open(repo).begin("t1")
    t.record_read("new.py")
    assert isinstance(t.validate_write("new.py", scope="target"), Ok)


def test_should_block_blind_overwrite_when_file_exists_and_never_read(repo: Path) -> None:
    _write(repo, "a.py", "one")
    t = Ledger.open(repo).begin("t1")
    result = t.validate_write("a.py", scope="target")
    assert isinstance(result, Conflict)
    assert result.kind == "blind_overwrite"
    assert result.ok is False
    assert "never read" in result.message


def test_should_block_stale_read_when_disk_changed_after_read(repo: Path) -> None:
    _write(repo, "a.py", "one\n")
    ledger = Ledger.open(repo)
    a = ledger.begin("a")
    a.record_read("a.py")
    _write(repo, "a.py", "two\n")
    result = a.validate_write("a.py", scope="target")
    assert isinstance(result, Conflict)
    assert result.kind == "stale_read"
    assert "-one" in result.diff and "+two" in result.diff
    assert "a.py" in result.message
    assert "Changed by" not in result.message


def test_should_block_when_file_created_after_absent_read(repo: Path) -> None:
    t = Ledger.open(repo).begin("t1")
    t.record_read("new.py")
    _write(repo, "new.py", "someone else\n")
    result = t.validate_write("new.py", scope="target")
    assert isinstance(result, Conflict)
    assert result.expected_hash == ABSENT
    assert "did not exist when you read it" in result.diff


def test_should_not_conflict_when_writing_own_change(repo: Path) -> None:
    _write(repo, "a.py", "one")
    t = Ledger.open(repo).begin("t1")
    t.record_read("a.py")
    _write(repo, "a.py", "mine")
    t.record_write("a.py")
    assert isinstance(t.validate_write("a.py", scope="target"), Ok)


def test_should_attribute_change_when_other_transaction_wrote_it(repo: Path) -> None:
    _write(repo, "a.py", "one\n")
    ledger = Ledger.open(repo)
    a = ledger.begin("agent-a")
    b = ledger.begin("agent-b", kind="agent", agent_type="Explore")
    a.record_read("a.py")
    b.record_read("a.py")
    _write(repo, "a.py", "two\n")
    b.record_write("a.py")
    result = a.validate_write("a.py", scope="target")
    assert isinstance(result, Conflict)
    assert result.changed_by == "agent-b"
    assert result.changed_by_type == "Explore"
    assert "Changed by: agent-b (Explore)" in result.message


def test_should_attribute_blind_overwrite_when_other_transaction_created_file(repo: Path) -> None:
    ledger = Ledger.open(repo)
    b = ledger.begin("agent-b")
    _write(repo, "a.py", "b made this\n")
    b.record_write("a.py")
    a = ledger.begin("agent-a")
    result = a.validate_write("a.py", scope="target")
    assert isinstance(result, Conflict)
    assert result.kind == "blind_overwrite"
    assert result.changed_by == "agent-b"


def test_should_log_conflict_when_detected(repo: Path) -> None:
    _write(repo, "a.py", "one\n")
    ledger = Ledger.open(repo)
    a = ledger.begin("a")
    a.record_read("a.py")
    _write(repo, "a.py", "two\n")
    a.validate_write("a.py", scope="target", tool_use_id="toolu_1")
    with ledger.connect() as conn:
        rows = conn.execute("select * from conflict_log").fetchall()
    assert len(rows) == 1
    assert rows[0]["tool_use_id"] == "toolu_1"
    assert rows[0]["kind"] == "stale_read"


def test_should_block_when_file_deleted_after_read(repo: Path) -> None:
    _write(repo, "a.py", "one\n")
    t = Ledger.open(repo).begin("t1")
    t.record_read("a.py")
    (repo / "a.py").unlink()
    result = t.validate_write("a.py", scope="target")
    assert isinstance(result, Conflict)
    assert result.actual_hash == ABSENT
    assert "deleted" in result.diff


def test_should_record_absent_when_own_write_deleted_file(repo: Path) -> None:
    _write(repo, "a.py", "one\n")
    t = Ledger.open(repo).begin("t1")
    t.record_read("a.py")
    (repo / "a.py").unlink()
    assert t.record_write("a.py") == ABSENT
    assert isinstance(t.validate_write("a.py", scope="target"), Ok)
