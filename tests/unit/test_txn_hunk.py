from __future__ import annotations

from pathlib import Path

from readset.ledger import Ledger
from readset.txn import Conflict, Ok

TEN = "".join(f"line{i}\n" for i in range(1, 11))


def _write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).write_text(text)


def test_should_allow_edit_when_other_change_is_far_away(repo: Path) -> None:
    _write(repo, "f.py", TEN)
    ledger = Ledger.open(repo)
    a = ledger.begin("a")
    a.record_read("f.py")
    b = ledger.begin("b")
    b.record_read("f.py")
    _write(repo, "f.py", TEN.replace("line1\n", "LINE1\n"))
    b.record_write("f.py")
    result = a.validate_write("f.py", scope="hunk", edits=[("line9\n", "nine\n")])
    assert isinstance(result, Ok)
    assert "changed since you read it" in result.notice
    assert "-line1" in result.notice and "+LINE1" in result.notice
    assert "changed by b" in result.notice


def test_should_block_edit_when_other_change_overlaps_region(repo: Path) -> None:
    _write(repo, "f.py", TEN)
    ledger = Ledger.open(repo)
    a = ledger.begin("a")
    a.record_read("f.py")
    _write(repo, "f.py", TEN.replace("line5\n", "FIVE\n"))
    result = a.validate_write("f.py", scope="hunk", edits=[("line5\n", "five\n")])
    assert isinstance(result, Conflict)
    assert result.kind == "stale_read"
    assert "region you are editing" in result.message


def test_should_block_edit_when_within_margin_of_other_change(repo: Path) -> None:
    _write(repo, "f.py", TEN)
    ledger = Ledger.open(repo)
    a = ledger.begin("a")
    a.record_read("f.py")
    _write(repo, "f.py", TEN.replace("line5\n", "FIVE\n"))
    near = a.validate_write("f.py", scope="hunk", edits=[("line7\n", "seven\n")], hunk_margin=3)
    assert isinstance(near, Conflict)
    far = a.validate_write("f.py", scope="hunk", edits=[("line7\n", "seven\n")], hunk_margin=1)
    assert isinstance(far, Ok)


def test_should_block_when_edit_targets_text_agent_never_saw(repo: Path) -> None:
    _write(repo, "f.py", TEN)
    ledger = Ledger.open(repo)
    a = ledger.begin("a")
    a.record_read("f.py")
    _write(repo, "f.py", TEN + "extra\n")
    result = a.validate_write("f.py", scope="hunk", edits=[("extra\n", "more\n")])
    assert isinstance(result, Conflict)


def test_should_block_when_replace_all_requested_on_stale_file(repo: Path) -> None:
    _write(repo, "f.py", TEN)
    ledger = Ledger.open(repo)
    a = ledger.begin("a")
    a.record_read("f.py")
    _write(repo, "f.py", TEN.replace("line1\n", "LINE1\n"))
    result = a.validate_write("f.py", scope="hunk", edits=[("line9\n", "nine\n")], replace_all=True)
    assert isinstance(result, Conflict)


def test_should_block_full_write_when_file_stale_even_in_hunk_scope(repo: Path) -> None:
    _write(repo, "f.py", TEN)
    ledger = Ledger.open(repo)
    a = ledger.begin("a")
    a.record_read("f.py")
    _write(repo, "f.py", TEN.replace("line1\n", "LINE1\n"))
    assert isinstance(a.validate_write("f.py", scope="hunk"), Conflict)


def test_should_keep_protecting_unseen_region_after_hunk_allow(repo: Path) -> None:
    _write(repo, "f.py", TEN)
    ledger = Ledger.open(repo)
    a = ledger.begin("a")
    a.record_read("f.py")
    _write(repo, "f.py", TEN.replace("line1\n", "LINE1\n"))
    assert isinstance(a.validate_write("f.py", scope="hunk", edits=[("line9\n", "nine\n")]), Ok)
    _write(repo, "f.py", TEN.replace("line1\n", "LINE1\n").replace("line9\n", "nine\n"))
    a.record_write("f.py", edits=[("line9\n", "nine\n")])
    later = a.validate_write("f.py", scope="hunk", edits=[("line1\n", "one\n")])
    assert isinstance(later, Conflict)
    fine = a.validate_write("f.py", scope="hunk", edits=[("line8\n", "eight\n")], hunk_margin=0)
    assert isinstance(fine, Ok)


def test_should_warn_not_block_when_sibling_stale_in_hunk_scope(repo: Path) -> None:
    _write(repo, "auth.py", "v1\n")
    _write(repo, "models.py", "m1\n")
    a = Ledger.open(repo).begin("a")
    a.record_read("auth.py")
    a.record_read("models.py")
    _write(repo, "auth.py", "v2\n")
    result = a.validate_write("models.py", scope="hunk", edits=[("m1\n", "m2\n")])
    assert isinstance(result, Ok)
    assert "auth.py" in result.notice


def test_should_return_plain_ok_when_nothing_changed_in_hunk_scope(repo: Path) -> None:
    _write(repo, "f.py", TEN)
    a = Ledger.open(repo).begin("a")
    a.record_read("f.py")
    result = a.validate_write("f.py", scope="hunk", edits=[("line1\n", "x\n")])
    assert isinstance(result, Ok)
    assert result.notice == ""


def test_should_fall_back_to_disk_hash_when_edits_do_not_apply_to_view(repo: Path) -> None:
    _write(repo, "f.py", TEN)
    a = Ledger.open(repo).begin("a")
    a.record_read("f.py")
    _write(repo, "f.py", "rewritten\n")
    digest = a.record_write("f.py", edits=[("nope\n", "x\n")])
    assert a.read_set()["f.py"] == digest
    assert isinstance(a.validate_write("f.py", scope="target"), Ok)
