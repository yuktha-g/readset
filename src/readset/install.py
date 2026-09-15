"""Installing and removing readset's hooks in a Claude Code settings.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

Agent = Literal["claude", "codex"]
AGENTS: tuple[Agent, ...] = ("claude", "codex")

WRITE_MATCHER = "Edit|Write|MultiEdit|NotebookEdit"
POST_MATCHER = "Read|Edit|Write|MultiEdit|NotebookEdit|Bash"
CODEX_PATCH_MATCHER = "apply_patch"
CODEX_POST_MATCHER = "apply_patch|Bash"
GITIGNORE_LINE = ".readset/"
HOOK_TIMEOUT_SECONDS = 10


def _handler(executable: str, agent: Agent) -> dict[str, Any]:
    suffix = "" if agent == "claude" else f" --agent {agent}"
    return {
        "type": "command",
        "command": f"{executable} hook{suffix}",
        "timeout": HOOK_TIMEOUT_SECONDS,
    }


def hook_config(executable: str, agent: Agent = "claude") -> dict[str, list[dict[str, Any]]]:
    """The hook groups readset needs for an agent, keyed by event name."""
    handler = _handler(executable, agent)
    if agent == "codex":
        return {
            "PreToolUse": [{"matcher": CODEX_PATCH_MATCHER, "hooks": [handler]}],
            "PostToolUse": [{"matcher": CODEX_POST_MATCHER, "hooks": [handler]}],
            "SessionStart": [{"matcher": "*", "hooks": [handler]}],
            "SessionEnd": [{"matcher": "*", "hooks": [handler]}],
        }
    return {
        "PreToolUse": [{"matcher": WRITE_MATCHER, "hooks": [handler]}],
        "PostToolUse": [{"matcher": POST_MATCHER, "hooks": [handler]}],
        "SubagentStart": [{"matcher": "*", "hooks": [handler]}],
        "SubagentStop": [{"matcher": "*", "hooks": [handler]}],
        "SessionStart": [{"matcher": "*", "hooks": [handler]}],
        "SessionEnd": [{"matcher": "*", "hooks": [handler]}],
    }


def settings_file(agent: Agent, root: Path, *, user: bool) -> Path:
    """Where each agent keeps its hooks configuration."""
    base = Path.home() if user else root
    if agent == "codex":
        return base / ".codex" / "hooks.json"
    return base / ".claude" / "settings.json"


def is_readset_hook(handler: dict[str, Any], agent: Agent | None = None) -> bool:
    """True for a handler readset installed, regardless of the executable path.

    With `agent`, only handlers installed for that agent match.
    """
    command = handler.get("command")
    if not (isinstance(command, str) and "readset" in command and " hook" in command):
        return False
    if agent is None:
        return True
    is_codex = "--agent codex" in command
    return is_codex if agent == "codex" else not is_codex


def _load(settings_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(settings_path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(settings_path: Path, data: dict[str, Any]) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n")


def _strip(hooks: dict[str, Any], agent: Agent | None = None) -> tuple[dict[str, Any], bool]:
    """Remove readset handlers (for one agent, or all) from a hooks mapping.

    Returns (new mapping, changed).

    Anything that does not look like a hook group is passed through untouched.
    """
    changed = False
    out: dict[str, Any] = {}
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            out[event] = groups
            continue
        kept_groups: list[Any] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept_groups.append(group)
                continue
            handlers = [
                h for h in group["hooks"] if not (isinstance(h, dict) and is_readset_hook(h, agent))
            ]
            if len(handlers) != len(group["hooks"]):
                changed = True
            if handlers:
                kept_groups.append({**group, "hooks": handlers})
        if kept_groups:
            out[event] = kept_groups
    return out, changed


def install_hooks(settings_path: Path, executable: str, agent: Agent = "claude") -> bool:
    """Merge readset's hooks into a hooks file. Returns True if the file changed."""
    data = _load(settings_path)
    raw = data.get("hooks")
    existing: dict[str, Any] = raw if isinstance(raw, dict) else {}
    stripped, _ = _strip(existing, agent)
    merged = dict(stripped)
    for event, groups in hook_config(executable, agent).items():
        current = merged.get(event, [])
        if not isinstance(current, list):
            current = [current]
        merged[event] = [*current, *groups]
    if existing == merged:
        return False
    data["hooks"] = merged
    _save(settings_path, data)
    return True


def remove_hooks(settings_path: Path) -> bool:
    """Remove exactly the hooks readset installed. Returns True if the file changed."""
    data = _load(settings_path)
    raw = data.get("hooks")
    existing: dict[str, Any] = raw if isinstance(raw, dict) else {}
    stripped, changed = _strip(existing)
    if not changed:
        return False
    data["hooks"] = stripped
    _save(settings_path, data)
    return True


def ensure_gitignore(root: Path) -> bool:
    """Add .readset/ to the repo's .gitignore. Returns True if the file changed."""
    gitignore = root / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    if GITIGNORE_LINE in existing.splitlines():
        return False
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    gitignore.write_text(existing + prefix + GITIGNORE_LINE + "\n")
    return True


def ensure_git_exclude(root: Path) -> bool:
    """Add .readset/ to .git/info/exclude (local, never committed). Returns True if changed.

    Used by the plugin's auto-init so opening a repo never modifies a tracked file.
    """
    git_dir = root / ".git"
    if not git_dir.is_dir():
        return False
    exclude = git_dir / "info" / "exclude"
    existing = exclude.read_text() if exclude.exists() else ""
    if GITIGNORE_LINE in existing.splitlines():
        return False
    exclude.parent.mkdir(parents=True, exist_ok=True)
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    exclude.write_text(existing + prefix + GITIGNORE_LINE + "\n")
    return True
