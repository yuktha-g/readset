from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from readset.hooks.codex import dispatch
from readset.ledger import Ledger

TEN = "".join(f"line{i}\n" for i in range(1, 11))


def _p(repo: Path, event: str, tool: str | None = None, command: str = "") -> dict[str, Any]:
    p: dict[str, Any] = {
        "session_id": "codex-1",
        "hook_event_name": event,
        "cwd": str(repo),
        "tool_use_id": "call_1",
    }
    if tool is not None:
        p["tool_name"] = tool
        p["tool_input"] = {"command": command}
    return p


def _patch(path: str, old: str, new: str) -> str:
    return f"*** Begin Patch\n*** Update File: {path}\n@@\n-{old}\n+{new}\n*** End Patch\n"


def test_should_noop_when_not_initialised(repo: Path) -> None:
    assert dispatch(_p(repo, "PostToolUse", "Bash", "cat a.py")).action == "noop"


def test_should_record_reads_for_files_named_in_shell_command(repo: Path) -> None:
    ledger = Ledger.open(repo)
    (repo / "a.py").write_text("x")
    (repo / "b.py").write_text("y")
    r = dispatch(_p(repo, "PostToolUse", "Bash", "cat a.py && sed -n '1,5p' b.py | head"))
    assert r.action == "bash:a.py,b.py"
    assert set(ledger.begin("codex-1").read_set()) == {"a.py", "b.py"}


def test_should_skip_nonexistent_and_flag_tokens_when_scanning_command(repo: Path) -> None:
    Ledger.open(repo)
    (repo / "a.py").write_text("x")
    r = dispatch(_p(repo, "PostToolUse", "Bash", "rg -n pattern nope.py a.py --type py"))
    assert r.action == "bash:a.py"


def test_should_refresh_when_shell_edits_file_already_read(repo: Path) -> None:
    ledger = Ledger.open(repo)
    (repo / "a.py").write_text("v1\n")
    dispatch(_p(repo, "PostToolUse", "Bash", "cat a.py"))
    (repo / "a.py").write_text("v2\n")
    dispatch(_p(repo, "PostToolUse", "Bash", "sed -i s/v1/v2/ a.py"))
    t = ledger.begin("codex-1")
    assert t.validate_write("a.py", scope="target").ok


def test_should_deny_patch_when_region_changed_by_other_session(repo: Path) -> None:
    ledger = Ledger.open(repo)
    (repo / "f.py").write_text(TEN)
    dispatch(_p(repo, "PostToolUse", "Bash", "cat f.py"))
    other = ledger.begin("other")
    other.record_read("f.py")
    (repo / "f.py").write_text(TEN.replace("line5\n", "FIVE\n"))
    other.record_write("f.py")
    r = dispatch(_p(repo, "PreToolUse", "apply_patch", _patch("f.py", "line5", "five")))
    assert r.action == "deny"
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "Changed by: other" in out["permissionDecisionReason"]


def test_should_allow_patch_with_notice_when_change_is_elsewhere(repo: Path) -> None:
    ledger = Ledger.open(repo)
    (repo / "f.py").write_text(TEN)
    dispatch(_p(repo, "PostToolUse", "Bash", "cat f.py"))
    other = ledger.begin("other")
    other.record_read("f.py")
    (repo / "f.py").write_text(TEN.replace("line1\n", "ONE\n"))
    other.record_write("f.py")
    r = dispatch(_p(repo, "PreToolUse", "apply_patch", _patch("f.py", "line9", "nine")))
    assert r.action == "allow+notice"
    assert "heads-up" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_should_block_blind_overwrite_via_add_file_when_file_exists(repo: Path) -> None:
    Ledger.open(repo)
    (repo / "exists.py").write_text("x")
    patch = "*** Begin Patch\n*** Add File: exists.py\n+new\n*** End Patch\n"
    assert dispatch(_p(repo, "PreToolUse", "apply_patch", patch)).action == "deny"


def test_should_allow_add_file_when_file_absent(repo: Path) -> None:
    Ledger.open(repo)
    patch = "*** Begin Patch\n*** Add File: fresh.py\n+new\n*** End Patch\n"
    assert dispatch(_p(repo, "PreToolUse", "apply_patch", patch)).action == "allow"


def test_should_record_writes_for_every_patched_file(repo: Path) -> None:
    ledger = Ledger.open(repo)
    (repo / "a.py").write_text("x\n")
    (repo / "b.py").write_text("y\n")
    dispatch(_p(repo, "PostToolUse", "Bash", "cat a.py b.py"))
    (repo / "a.py").write_text("X\n")
    (repo / "b.py").write_text("Y\n")
    patch = (
        "*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+X\n"
        "*** Update File: b.py\n*** Move to: c.py\n@@\n-y\n+Y\n*** End Patch\n"
    )
    (repo / "c.py").write_text("Y\n")
    r = dispatch(_p(repo, "PostToolUse", "apply_patch", patch))
    assert r.action == "write:a.py,b.py,c.py"
    t = ledger.begin("codex-1")
    assert t.validate_write("a.py", scope="target").ok
    assert t.validate_write("c.py", scope="target").ok


def test_should_noop_when_patch_is_not_a_patch(repo: Path) -> None:
    Ledger.open(repo)
    assert dispatch(_p(repo, "PreToolUse", "apply_patch", "garbage")).action == "noop"
    assert dispatch(_p(repo, "PreToolUse", "mcp__fs__read", "x")).action == "noop"
    assert dispatch(_p(repo, "PreToolUse", "Bash", "ls")).action == "noop"
    assert dispatch(_p(repo, "Notification")).action == "noop"


def test_should_ignore_paths_outside_repo_or_ignored(repo: Path, tmp_path: Path) -> None:
    Ledger.open(repo)
    outside = tmp_path.parent / "x.py"
    patch = f"*** Begin Patch\n*** Add File: {outside}\n+z\n*** End Patch\n"
    assert dispatch(_p(repo, "PreToolUse", "apply_patch", patch)).action == "allow"
    patch2 = "*** Begin Patch\n*** Add File: .readset/x\n+z\n*** End Patch\n"
    assert dispatch(_p(repo, "PostToolUse", "apply_patch", patch2)).action == "noop"


def test_should_begin_and_end_session_when_lifecycle_events_fire(repo: Path) -> None:
    ledger = Ledger.open(repo)
    assert dispatch(_p(repo, "SessionStart")).action == "begin"
    assert dispatch(_p(repo, "SessionEnd")).action == "end"
    info = ledger.get("codex-1")
    assert info is not None and info.ended_at is not None and info.agent_type == "codex"


def test_should_noop_when_session_id_missing(repo: Path) -> None:
    Ledger.open(repo)
    p = _p(repo, "PostToolUse", "Bash", "ls")
    p["session_id"] = ""
    assert dispatch(p).action == "noop"


def test_should_tolerate_unbalanced_quotes_when_scanning_command(repo: Path) -> None:
    Ledger.open(repo)
    (repo / "a.py").write_text("x")
    assert dispatch(_p(repo, "PostToolUse", "Bash", "echo 'unbalanced a.py")).action == "bash:a.py"
