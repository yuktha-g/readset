from __future__ import annotations

from pathlib import Path

from readset.ledger import Ledger
from readset.txn import Conflict, Ok


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_should_block_when_sibling_stale_and_scope_is_strict(repo: Path) -> None:
    _write(repo, "auth.py", "v1\n")
    _write(repo, "models.py", "m1\n")
    t = Ledger.open(repo).begin("a")
    t.record_read("auth.py")
    t.record_read("models.py")
    _write(repo, "auth.py", "v2\n")
    result = t.validate_write("models.py", scope="strict")
    assert isinstance(result, Conflict)
    assert result.kind == "stale_dependency"
    assert result.stale_paths == ["auth.py"]
    assert "auth.py" in result.message and "models.py" in result.message
    assert "-v1" in result.diff and "+v2" in result.diff


def test_should_allow_when_sibling_stale_and_scope_is_target(repo: Path) -> None:
    _write(repo, "auth.py", "v1\n")
    _write(repo, "models.py", "m1\n")
    t = Ledger.open(repo).begin("a")
    t.record_read("auth.py")
    t.record_read("models.py")
    _write(repo, "auth.py", "v2\n")
    assert isinstance(t.validate_write("models.py", scope="target"), Ok)


def test_should_list_all_stale_when_target_and_siblings_stale(repo: Path) -> None:
    for p in ("a.py", "b.py", "c.py"):
        _write(repo, p, "1\n")
    t = Ledger.open(repo).begin("a")
    for p in ("a.py", "b.py", "c.py"):
        t.record_read(p)
    for p in ("a.py", "b.py", "c.py"):
        _write(repo, p, "2\n")
    result = t.validate_write("a.py", scope="strict")
    assert isinstance(result, Conflict)
    assert result.kind == "stale_read"
    assert result.stale_paths == ["b.py", "c.py"]
    assert "Also stale in your read set: b.py, c.py" in result.message


def test_should_allow_after_reread_when_previously_stale(repo: Path) -> None:
    _write(repo, "auth.py", "v1\n")
    t = Ledger.open(repo).begin("a")
    t.record_read("auth.py")
    _write(repo, "auth.py", "v2\n")
    assert isinstance(t.validate_write("auth.py"), Conflict)
    t.record_read("auth.py")
    assert isinstance(t.validate_write("auth.py"), Ok)


def test_should_default_to_hunk_scope_when_not_given(repo: Path) -> None:
    _write(repo, "auth.py", "v1\n")
    _write(repo, "models.py", "m1\n")
    t = Ledger.open(repo).begin("a")
    t.record_read("auth.py")
    t.record_read("models.py")
    _write(repo, "auth.py", "v2\n")
    result = t.validate_write("models.py", edits=[("m1\n", "m2\n")])
    assert isinstance(result, Ok)
    assert "auth.py" in result.notice
