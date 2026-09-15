from __future__ import annotations

from readset.diff import human_age, unified


def test_should_render_unified_diff_when_text_changes() -> None:
    out = unified(b"a\nb\n", b"a\nc\n", "f.py", old_label="read", new_label="disk", max_lines=50)
    assert "--- f.py (read)" in out
    assert "+++ f.py (disk)" in out
    assert "-b" in out and "+c" in out


def test_should_truncate_when_diff_exceeds_max_lines() -> None:
    old = "".join(f"{i}\n" for i in range(100)).encode()
    new = "".join(f"{i}x\n" for i in range(100)).encode()
    out = unified(old, new, "f", old_label="a", new_label="b", max_lines=10)
    assert out.count("\n") <= 12
    assert "truncated" in out


def test_should_describe_binary_when_bytes_contain_nul() -> None:
    out = unified(
        b"\x00\x01", b"\x00\x02\x03", "img.bin", old_label="a", new_label="b", max_lines=10
    )
    assert "binary" in out
    assert "2 -> 3 bytes" in out


def test_should_describe_creation_and_deletion_when_one_side_missing() -> None:
    created = unified(None, b"x\n", "f", old_label="a", new_label="b", max_lines=10)
    deleted = unified(b"x\n", None, "f", old_label="a", new_label="b", max_lines=10)
    neither = unified(None, None, "f", old_label="a", new_label="b", max_lines=10)
    assert "did not exist" in created
    assert "deleted" in deleted
    assert "either side" in neither


def test_should_humanise_age_when_given_seconds() -> None:
    assert human_age(5) == "5s ago"
    assert human_age(125) == "2m ago"
    assert human_age(7300) == "2h ago"
    assert human_age(90000) == "1d ago"
    assert human_age(-3) == "0s ago"
