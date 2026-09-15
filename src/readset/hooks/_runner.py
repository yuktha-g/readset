"""Shared plumbing for hook adapters: the result type and the fail-open entry point."""

from __future__ import annotations

import json
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from readset.paths import LEDGER_DIR, find_ledger_root

ERROR_LOG = "errors.log"


@dataclass(frozen=True)
class HookResult:
    """What the hook prints and how it exits. `action` names what happened, for tests and logs."""

    stdout: str = ""
    exit_code: int = 0
    action: str = "noop"


def deny(reason: str) -> HookResult:
    """A PreToolUse block. The reason is shown to the model."""
    body = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    return HookResult(stdout=json.dumps(body), action="deny")


def allow(notice: str = "") -> HookResult:
    """A PreToolUse allow, optionally with context the model sees."""
    if not notice:
        return HookResult(action="allow")
    body = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "additionalContext": notice,
        }
    }
    return HookResult(stdout=json.dumps(body), action="allow+notice")


def run(dispatch: Callable[[dict[str, Any]], HookResult], stdin: IO[str], stdout: IO[str]) -> int:
    """Fail-open entry point. Always returns 0; internal errors go to .readset/errors.log."""
    raw = stdin.read()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return 0
        result = dispatch(payload)
    except Exception:  # fail-open by design; the traceback is logged
        _log_error(raw)
        return 0
    if result.stdout:
        stdout.write(result.stdout)
    return result.exit_code


def _log_error(raw: str) -> None:
    cwd = "."
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            cwd = str(parsed.get("cwd", "."))
    except ValueError:
        pass
    root = find_ledger_root(Path(cwd))
    if root is None:
        return
    try:
        with (root / LEDGER_DIR / ERROR_LOG).open("a") as fh:
            fh.write(traceback.format_exc())
            fh.write("\n")
    except OSError:
        return
