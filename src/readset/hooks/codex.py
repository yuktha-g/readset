"""Codex CLI adapter: maps Codex hook events onto readset transactions.

Codex differs from Claude Code in two ways that matter here:

- There is no Read tool. Files are read through shell commands (`cat`, `sed -n`, `rg`).
  After every `Bash` call, any existing repository file named in the command is treated as
  read; a file already in the read set whose content changed is treated as this session's
  own write (e.g. `sed -i`).
- Edits arrive as one `apply_patch` command that can touch several files. Each
  `*** Update File` hunk becomes an (old, new) replacement so hunk-level validation applies;
  `*** Add File` is a creation and `*** Delete File` a whole-file write.

Payload shape and the deny / additionalContext output follow the Codex hooks reference and
match Claude Code's. This adapter is exercised by unit tests against documented payloads;
it has not yet been run against a live Codex install.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import IO, Any

from readset.config import load as load_config
from readset.errors import OutsideRepoError
from readset.hooks._runner import HookResult, allow, deny, run
from readset.hooks.apply_patch import parse_patch
from readset.ledger import Ledger
from readset.paths import find_ledger_root, is_ignored, relative_path
from readset.txn import Conflict, Transaction

SHELL_TOOLS = frozenset({"Bash", "exec_command", "shell"})
PATCH_TOOLS = frozenset({"apply_patch"})
MAX_COMMAND_TOKENS = 64


def dispatch(payload: dict[str, Any]) -> HookResult:
    """Handle one Codex hook payload. Raises on internal errors; `main` catches them."""
    root = find_ledger_root(Path(str(payload.get("cwd", "."))))
    if root is None:
        return HookResult()
    event = str(payload.get("hook_event_name", ""))
    session_id = str(payload.get("session_id") or "")
    if not session_id:
        return HookResult()

    ledger = Ledger.open(root)
    config = load_config(root)
    txn = ledger.begin(session_id, kind="session", agent_type="codex")

    if event == "SessionStart":
        return HookResult(action="begin")
    if event == "SessionEnd":
        txn.end()
        return HookResult(action="end")
    if event not in ("PreToolUse", "PostToolUse"):
        return HookResult()

    tool = str(payload.get("tool_name", ""))
    raw_input = payload.get("tool_input")
    tool_input: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
    command = str(tool_input.get("command", ""))
    tool_use_id = payload.get("tool_use_id")
    tool_use_id = str(tool_use_id) if tool_use_id else None

    if tool in SHELL_TOOLS:
        if event != "PostToolUse":
            return HookResult()
        seen = _observe_command(txn, root, command, config.ignore)
        return HookResult(action="bash:" + ",".join(seen)) if seen else HookResult()

    if tool not in PATCH_TOOLS:
        return HookResult()

    files = parse_patch(command)
    if not files:
        return HookResult()

    if event == "PreToolUse":
        reasons: list[str] = []
        notices: list[str] = []
        for item in files:
            rel = _relative(root, item.path)
            if rel is None or is_ignored(rel, config.ignore):
                continue
            result = txn.validate_write(
                rel,
                scope=config.scope,
                edits=item.edits if item.op == "update" else None,
                hunk_margin=config.hunk_margin,
                tool_use_id=tool_use_id,
                diff_max_lines=config.diff_max_lines,
            )
            if isinstance(result, Conflict):
                reasons.append(result.message)
            elif result.notice:
                notices.append(result.notice)
        if reasons:
            return deny("\n\n".join(reasons))
        return allow("\n\n".join(notices))

    written: list[str] = []
    for item in files:
        rel = _relative(root, item.path)
        if rel is None or is_ignored(rel, config.ignore):
            continue
        txn.record_write(
            rel, edits=item.edits if item.op == "update" else None, tool_use_id=tool_use_id
        )
        written.append(rel)
        if item.move_to:
            target = _relative(root, item.move_to)
            if target is not None and not is_ignored(target, config.ignore):
                txn.record_write(target, tool_use_id=tool_use_id)
                written.append(target)
    return HookResult(action="write:" + ",".join(written)) if written else HookResult()


def _observe_command(
    txn: Transaction, root: Path, command: str, ignore: tuple[str, ...]
) -> list[str]:
    """Record every existing repo file named in a shell command as read (or refreshed)."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    seen: list[str] = []
    known = txn.read_set()
    for token in tokens[:MAX_COMMAND_TOKENS]:
        candidate = token.strip("<>|;&()'\"")
        if not candidate or candidate.startswith("-"):
            continue
        rel = _relative(root, candidate)
        if rel is None or is_ignored(rel, ignore) or not (root / rel).is_file():
            continue
        if rel in known:
            txn.refresh_mentioned(rel)
        else:
            txn.record_read(rel)
        seen.append(rel)
    return seen


def _relative(root: Path, raw: str) -> str | None:
    try:
        return relative_path(root, raw)
    except OutsideRepoError:
        return None


def main(stdin: IO[str], stdout: IO[str]) -> int:
    """Fail-open entry point used by `readset hook --agent codex`. Always returns 0."""
    return run(dispatch, stdin, stdout)
