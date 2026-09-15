from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from readset.hooks.claude_code import dispatch, main
from readset.ledger import Ledger


def _init(repo: Path) -> Ledger:
    return Ledger.open(repo)


def _payload(repo: Path, event: str, tool: str | None = None, **tool_input: Any) -> dict[str, Any]:
    p: dict[str, Any] = {
        "session_id": "sess-1",
        "hook_event_name": event,
        "cwd": str(repo),
        "tool_use_id": "toolu_1",
    }
    if tool is not None:
        p["tool_name"] = tool
        p["tool_input"] = tool_input
    return p


def test_should_noop_when_repo_not_initialised(repo: Path) -> None:
    r = dispatch(_payload(repo, "PostToolUse", "Read", file_path=str(repo / "a.py")))
    assert r.action == "noop"
    assert not (repo / ".readset").exists()


def test_should_noop_when_no_identity_in_payload(repo: Path) -> None:
    _init(repo)
    p = _payload(repo, "PostToolUse", "Read", file_path="a.py")
    p["session_id"] = ""
    assert dispatch(p).action == "noop"


def test_should_record_read_when_read_tool_succeeds(repo: Path) -> None:
    ledger = _init(repo)
    (repo / "a.py").write_text("x")
    r = dispatch(_payload(repo, "PostToolUse", "Read", file_path=str(repo / "a.py")))
    assert r.action == "read"
    assert "a.py" in ledger.begin("sess-1").read_set()


def test_should_use_agent_id_as_identity_when_present(repo: Path) -> None:
    ledger = _init(repo)
    (repo / "a.py").write_text("x")
    p = _payload(repo, "PostToolUse", "Read", file_path="a.py")
    p["agent_id"] = "agent-9"
    p["agent_type"] = "Explore"
    dispatch(p)
    assert "a.py" in ledger.begin("agent-9").read_set()
    info = ledger.get("agent-9")
    assert info is not None and info.parent_txn == "sess-1" and info.agent_type == "Explore"


def test_should_deny_with_reason_when_write_conflicts(repo: Path) -> None:
    _init(repo)
    (repo / "a.py").write_text("v1\n")
    dispatch(_payload(repo, "PostToolUse", "Read", file_path="a.py"))
    (repo / "a.py").write_text("v2\n")
    r = dispatch(
        _payload(repo, "PreToolUse", "Edit", file_path="a.py", old_string="v", new_string="w")
    )
    assert r.action == "deny"
    assert r.exit_code == 0
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "changed after you read it" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_should_allow_silently_when_write_is_safe(repo: Path) -> None:
    _init(repo)
    (repo / "a.py").write_text("v1\n")
    dispatch(_payload(repo, "PostToolUse", "Read", file_path="a.py"))
    r = dispatch(_payload(repo, "PreToolUse", "Edit", file_path="a.py"))
    assert r.action == "allow"
    assert r.stdout == ""


def test_should_record_write_when_write_tool_succeeds(repo: Path) -> None:
    ledger = _init(repo)
    (repo / "n.py").write_text("new")
    r = dispatch(_payload(repo, "PostToolUse", "Write", file_path="n.py"))
    assert r.action == "write"
    assert "n.py" in ledger.begin("sess-1").read_set()


def test_should_use_notebook_path_when_notebook_tool_used(repo: Path) -> None:
    ledger = _init(repo)
    (repo / "n.ipynb").write_text("{}")
    r = dispatch(_payload(repo, "PostToolUse", "NotebookEdit", notebook_path="n.ipynb"))
    assert r.action == "write"
    assert "n.ipynb" in ledger.begin("sess-1").read_set()


def test_should_refresh_mentioned_when_bash_ran(repo: Path) -> None:
    _init(repo)
    (repo / "a.py").write_text("v1\n")
    dispatch(_payload(repo, "PostToolUse", "Read", file_path="a.py"))
    (repo / "a.py").write_text("v2\n")
    r = dispatch(_payload(repo, "PostToolUse", "Bash", command="sed -i s/1/2/ a.py"))
    assert r.action == "bash:a.py"
    assert dispatch(_payload(repo, "PreToolUse", "Edit", file_path="a.py")).action == "allow"


def test_should_noop_when_bash_touches_nothing_tracked(repo: Path) -> None:
    _init(repo)
    assert dispatch(_payload(repo, "PostToolUse", "Bash", command="ls")).action == "noop"


def test_should_ignore_paths_matching_ignore_rules(repo: Path) -> None:
    _init(repo)
    r = dispatch(_payload(repo, "PostToolUse", "Read", file_path=".readset/ledger.db"))
    assert r.action == "noop"


def test_should_noop_when_path_outside_repo(repo: Path, tmp_path: Path) -> None:
    _init(repo)
    outside = tmp_path.parent / "elsewhere.py"
    r = dispatch(_payload(repo, "PostToolUse", "Read", file_path=str(outside)))
    assert r.action == "noop"


def test_should_noop_when_tool_input_has_no_path(repo: Path) -> None:
    _init(repo)
    assert dispatch(_payload(repo, "PostToolUse", "Read")).action == "noop"


def test_should_begin_and_end_subagent_when_lifecycle_events_fire(repo: Path) -> None:
    ledger = _init(repo)
    start = _payload(repo, "SubagentStart")
    start.update(agent_id="ag", agent_type="Plan")
    assert dispatch(start).action == "begin"
    stop = _payload(repo, "SubagentStop")
    stop.update(agent_id="ag", agent_type="Plan")
    assert dispatch(stop).action == "end"
    info = ledger.get("ag")
    assert info is not None and info.ended_at is not None


def test_should_end_session_when_session_end_fires(repo: Path) -> None:
    ledger = _init(repo)
    assert dispatch(_payload(repo, "SessionStart")).action == "begin"
    dispatch(_payload(repo, "SessionEnd"))
    info = ledger.get("sess-1")
    assert info is not None and info.ended_at is not None


def test_should_noop_when_tool_unknown(repo: Path) -> None:
    _init(repo)
    assert dispatch(_payload(repo, "PreToolUse", "Glob", pattern="*")).action == "noop"


def test_should_noop_when_event_unknown(repo: Path) -> None:
    _init(repo)
    assert dispatch(_payload(repo, "Notification", "Read", file_path="a.py")).action == "noop"


def test_should_fail_open_when_ledger_corrupt(repo: Path) -> None:
    ledger = _init(repo)
    ledger.db_path.write_bytes(b"garbage")
    payload = _payload(repo, "PreToolUse", "Edit", file_path="a.py")
    out = io.StringIO()
    code = main(io.StringIO(json.dumps(payload)), out)
    assert code == 0
    assert out.getvalue() == ""
    assert "DatabaseError" in (repo / ".readset" / "errors.log").read_text()


def test_should_fail_open_when_stdin_not_json(tmp_path: Path) -> None:
    out = io.StringIO()
    assert main(io.StringIO("not json"), out) == 0
    assert out.getvalue() == ""


def test_should_fail_open_when_payload_not_object(tmp_path: Path) -> None:
    out = io.StringIO()
    assert main(io.StringIO("[1]"), out) == 0
    assert out.getvalue() == ""


def test_should_write_deny_json_to_stdout_when_main_blocks(repo: Path) -> None:
    _init(repo)
    (repo / "a.py").write_text("v1\n")
    dispatch(_payload(repo, "PostToolUse", "Read", file_path="a.py"))
    (repo / "a.py").write_text("v2\n")
    out = io.StringIO()
    payload = _payload(repo, "PreToolUse", "Edit", file_path="a.py")
    assert main(io.StringIO(json.dumps(payload)), out) == 0
    assert json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecision"] == "deny"
