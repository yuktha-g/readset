from __future__ import annotations

from pathlib import Path

from readset.hashing import ABSENT, hash_bytes, read_and_hash


def test_should_hash_identically_when_bytes_equal() -> None:
    assert hash_bytes(b"abc") == hash_bytes(b"abc")
    assert hash_bytes(b"abc") != hash_bytes(b"abd")


def test_should_return_absent_when_file_missing(tmp_path: Path) -> None:
    digest, data = read_and_hash(tmp_path / "nope")
    assert digest == ABSENT
    assert data is None


def test_should_return_content_hash_when_file_exists(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_bytes(b"hello")
    digest, data = read_and_hash(f)
    assert digest == hash_bytes(b"hello")
    assert data == b"hello"


def test_should_return_absent_when_path_is_directory(tmp_path: Path) -> None:
    digest, data = read_and_hash(tmp_path)
    assert digest == ABSENT
    assert data is None
