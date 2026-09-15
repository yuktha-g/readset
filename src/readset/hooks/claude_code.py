"""Claude Code adapter: maps hook events onto readset transactions.

The entry point is `main`, which is fail-open: any internal error is logged to
.readset/errors.log and the tool call proceeds. A guard that can break a session is
worse than no guard.

Identity: a subagent's tool calls carry `agent_id`, which becomes the transaction id with
the session as parent. Everything else is keyed by `session_id`, so two Claude Code
terminals on one repo are two transactions.
"""

from __future__ import annotations

from pathlib import Path
from typing import IO, Any

from readset.config import load as load_config
from readset.errors import NotInRepoError, OutsideRepoError
from readset.hooks._runner import HookResult, allow, deny, run
from readset.install import ensure_git_exclude
from readset.ledger import Ledger
from readset.paths import find_ledger_root, find_repo_root, is_ignored, relative_path
from readset.txn import Conflict

READ_TOOLS = frozenset({"Read"})
WRITE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
PATH_FIELDS = ("file_path", "notebook_path")

__all__ = ["HookResult", "dispatch", "main"]


def dispatch(payload: dict[str, Any], *, auto_init: bool = False) -> HookResult:
    """Handle one hook payload. Raises on internal errors; `main` catches them.

    With `auto_init`, a SessionStart inside a git repository that has no ledger creates
    one at the git root and excludes it via .git/info/exclude. The plugin uses this so
    installing it is the only setup step.
    """
    cwd = Path(str(payload.get("cwd", ".")))
    root = find_ledger_root(cwd)
    if root is None and auto_init and payload.get("hook_event_name") == "SessionStart":
        root = _auto_init(cwd)
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
        edits, replace_all = _edits(tool, tool_input)
        result = txn.validate_write(
            rel,
            scope=config.scope,
            edits=edits,
            replace_all=replace_all,
            hunk_margin=config.hunk_margin,
            tool_use_id=tool_use_id,
            diff_max_lines=config.diff_max_lines,
        )
        if isinstance(result, Conflict):
            return deny(result.message)
        return allow(result.notice)

    if event == "PostToolUse" and tool in READ_TOOLS:
        txn.record_read(rel)
        return HookResult(action="read")

    if event == "PostToolUse" and tool in WRITE_TOOLS:
        edits, replace_all = _edits(tool, tool_input)
        txn.record_write(rel, edits=None if replace_all else edits, tool_use_id=tool_use_id)
        return HookResult(action="write")

    return HookResult()


def _edits(tool: str, tool_input: dict[str, Any]) -> tuple[list[tuple[str, str]] | None, bool]:
    """Extract (old, new) string replacements from Edit / MultiEdit input.

    Returns (None, False) for tools that replace the whole file (Write, NotebookEdit),
    so hunk-level validation does not apply to them.
    """
    if tool == "Edit":
        old, new = tool_input.get("old_string"), tool_input.get("new_string")
        if isinstance(old, str) and isinstance(new, str):
            return [(old, new)], bool(tool_input.get("replace_all", False))
        return None, False
    if tool == "MultiEdit":
        raw = tool_input.get("edits")
        if not isinstance(raw, list):
            return None, False
        edits: list[tuple[str, str]] = []
        replace_all = False
        for item in raw:
            if not isinstance(item, dict):
                return None, False
            old, new = item.get("old_string"), item.get("new_string")
            if not (isinstance(old, str) and isinstance(new, str)):
                return None, False
            edits.append((old, new))
            replace_all = replace_all or bool(item.get("replace_all", False))
        return edits, replace_all
    return None, False


def _auto_init(cwd: Path) -> Path | None:
    try:
        root = find_repo_root(cwd)
    except NotInRepoError:
        return None
    if not (root / ".git").exists():
        return None
    Ledger.open(root)
    ensure_git_exclude(root)
    return root


def _relative(root: Path, tool_input: dict[str, Any]) -> str | None:
    for field in PATH_FIELDS:
        raw = tool_input.get(field)
        if isinstance(raw, str) and raw:
            try:
                return relative_path(root, raw)
            except OutsideRepoError:
                return None
    return None


def main(stdin: IO[str], stdout: IO[str], *, auto_init: bool = False) -> int:
    """Fail-open entry point used by `readset hook`. Always returns 0."""
    return run(lambda payload: dispatch(payload, auto_init=auto_init), stdin, stdout)
