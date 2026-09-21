"""readset: snapshot isolation for AI agents."""

from __future__ import annotations

from readset.errors import (
    NotInRepoError,
    OutsideRepoError,
    ReadsetError,
    UnknownTransactionError,
)
from readset.ledger import GcReport, Ledger, TxnInfo
from readset.txn import Conflict, Ok, Result, Transaction

__version__ = "0.2.0"

__all__ = [
    "Conflict",
    "GcReport",
    "Ledger",
    "NotInRepoError",
    "Ok",
    "OutsideRepoError",
    "ReadsetError",
    "Result",
    "Transaction",
    "TxnInfo",
    "UnknownTransactionError",
    "__version__",
]
