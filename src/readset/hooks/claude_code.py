"""Claude Code adapter: maps hook events onto readset transactions.

The entry point is `main`, which is fail-open: any internal error is logged to
.readset/errors.log and the tool call proceeds. A guard that can break a session is
worse than no guard.

Identity: a subagent's tool calls carry `agent_id`, which becomes the transaction id with
the session as parent. Everything else is keyed by `session_id`, so two Claude Code
terminals on one repo are two transactions.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from readset.config import load as load_config
from readset.errors import OutsideRepoError
from readset.ledger import Ledger
from readset.paths import LEDGER_DIR, find_ledger_root, is_ignored, relative_path
from readset.txn import Conflict

READ_TOOLS = frozenset({"Read"})
WRITE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
PATH_FIELDS = ("file_path", "notebook_path")
ERROR_LOG = "errors.log"


@dataclass(frozen=True)
class HookResult:
    """What the hook prints and how it exits. `action` names what happened, for tests and logs."""

    stdout: str = ""
    exit_code: int = 0
    action: str = "noop"


def dispatch(payload: dict[str, Any]) -> HookResult:
    """Handle one hook payload. Raises on internal errors; `main` catches them."""
    root = find_ledger_root(Path(str(payload.get("cwd", "."))))
    if root is None:
        return HookResult()
    event = str(payload.get("hook_event_name", ""))
    session_id = str(payload.get("session_id") or "")
    agent_id = payload.get("agent_id")
    agent_type = payload.get("agent_type")
    if not session_id and not agent_id:
        return HookResult()

    ledger = Ledger.open(root)
    config = load_config(root)

    if agent_id:
        txn = ledger.begin(
            str(agent_id),
            kind="agent",
            parent=session_id or None,
            agent_type=str(agent_type) if agent_type else None,
        )
    else:
        txn = ledger.begin(session_id, kind="session")

    if event in ("SessionStart", "SubagentStart"):
        return HookResult(action="begin")
    if event in ("SubagentStop", "SessionEnd"):
        txn.end()
        return HookResult(action="end")
    if event not in ("PreToolUse", "PostToolUse"):
        return HookResult()

    tool = str(payload.get("tool_name", ""))
    raw_input = payload.get("tool_input")
    tool_input: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
    tool_use_id = payload.get("tool_use_id")
    tool_use_id = str(tool_use_id) if tool_use_id else None

    if event == "PostToolUse" and tool == "Bash":
        refreshed = txn.refresh_mentioned(str(tool_input.get("command", "")))
        return HookResult(action="bash:" + ",".join(refreshed)) if refreshed else HookResult()

    if tool not in READ_TOOLS and tool not in WRITE_TOOLS:
        return HookResult()

    rel = _relative(root, tool_input)
    if rel is None or is_ignored(rel, config.ignore):
        return HookResult()

    if event == "PreToolUse" and tool in WRITE_TOOLS:
        result = txn.validate_write(
            rel,
            scope=config.scope,
            tool_use_id=tool_use_id,
            diff_max_lines=config.diff_max_lines,
        )
        if not isinstance(result, Conflict):
            return HookResult(action="allow")
        body = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": result.message,
            }
        }
        return HookResult(stdout=json.dumps(body), action="deny")

    if event == "PostToolUse" and tool in READ_TOOLS:
        txn.record_read(rel)
        return HookResult(action="read")

    if event == "PostToolUse" and tool in WRITE_TOOLS:
        txn.record_write(rel, tool_use_id=tool_use_id)
        return HookResult(action="write")

    return HookResult()


def _relative(root: Path, tool_input: dict[str, Any]) -> str | None:
    for field in PATH_FIELDS:
        raw = tool_input.get(field)
        if isinstance(raw, str) and raw:
            try:
                return relative_path(root, raw)
            except OutsideRepoError:
                return None
    return None


def main(stdin: IO[str], stdout: IO[str]) -> int:
    """Fail-open entry point used by `readset hook`. Always returns 0."""
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
