"""Typed errors raised by readset. Nothing in readset raises a bare Exception."""

from __future__ import annotations


class ReadsetError(Exception):
    """Base class for every error readset raises."""


class NotInRepoError(ReadsetError):
    """Raised when no repository root can be found above a path."""

    def __init__(self, start: str) -> None:
        super().__init__(f"no .readset/ or .git/ directory found above {start}")
        self.start = start


class OutsideRepoError(ReadsetError):
    """Raised when a path resolves outside the repository root."""

    def __init__(self, path: str, root: str) -> None:
        super().__init__(f"{path} is outside the repository root {root}")
        self.path = path
        self.root = root


class UnknownTransactionError(ReadsetError):
    """Raised when a transaction id is not present in the ledger."""

    def __init__(self, txn_id: str) -> None:
        super().__init__(f"unknown transaction {txn_id!r}")
        self.txn_id = txn_id
