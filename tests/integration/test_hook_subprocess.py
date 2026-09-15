from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from readset.ledger import Ledger


def _run(payload: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "readset.cli", "hook"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def _p(repo: Path, session: str, event: str, tool: str, **tool_input: Any) -> dict[str, Any]:
    return {
        "session_id": session,
        "hook_event_name": event,
        "cwd": str(repo),
        "tool_name": tool,
        "tool_input": tool_input,
        "tool_use_id": "toolu_x",
    }


def test_should_deny_second_session_when_first_session_changed_file(repo: Path) -> None:
    Ledger.open(repo)
    (repo / "billing.py").write_text("rate = 0.18\n")
    assert _run(_p(repo, "A", "PostToolUse", "Read", file_path="billing.py")).returncode == 0
    assert _run(_p(repo, "B", "PostToolUse", "Read", file_path="billing.py")).returncode == 0
    (repo / "billing.py").write_text("rate = 0.20\n")
    assert _run(_p(repo, "B", "PostToolUse", "Edit", file_path="billing.py")).returncode == 0
    blocked = _run(_p(repo, "A", "PreToolUse", "Edit", file_path="billing.py"))
    assert blocked.returncode == 0, blocked.stderr
    out = json.loads(blocked.stdout)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "-rate = 0.18" in reason and "+rate = 0.20" in reason
    assert "Changed by: B" in reason


def test_should_exit_zero_with_no_output_when_ledger_corrupt(repo: Path) -> None:
    ledger = Ledger.open(repo)
    ledger.db_path.write_bytes(b"garbage")
    r = _run(_p(repo, "A", "PreToolUse", "Edit", file_path="x.py"))
    assert r.returncode == 0
    assert r.stdout == ""
    assert (repo / ".readset" / "errors.log").exists()


def test_should_route_to_codex_adapter_when_agent_flag_given(repo: Path) -> None:
    Ledger.open(repo)
    (repo / "a.py").write_text("v1\n")
    payload = {
        "session_id": "cx",
        "hook_event_name": "PostToolUse",
        "cwd": str(repo),
        "tool_name": "Bash",
        "tool_input": {"command": "cat a.py"},
    }
    r = subprocess.run(
        [sys.executable, "-m", "readset.cli", "hook", "--agent", "codex"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "a.py" in Ledger.open(repo).begin("cx").read_set()


def test_should_run_plugin_hook_script_from_source_when_python_present(repo: Path) -> None:
    script = Path(__file__).resolve().parents[2] / "hooks" / "readset-hook"
    payload = {"session_id": "plug", "hook_event_name": "SessionStart", "cwd": str(repo)}
    r = subprocess.run(
        [str(script), "--auto-init"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    assert (repo / ".readset" / "ledger.db").exists()
