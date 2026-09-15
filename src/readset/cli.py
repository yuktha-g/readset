"""Command-line interface. `readset hook` is the entry point Claude Code calls."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from readset import __version__
from readset._term import paint
from readset.config import Config, save
from readset.diff import human_age
from readset.errors import NotInRepoError
from readset.hooks import claude_code, codex
from readset.install import (
    AGENTS,
    Agent,
    ensure_gitignore,
    install_hooks,
    remove_hooks,
    settings_file,
)
from readset.ledger import Ledger
from readset.paths import LEDGER_DIR, find_ledger_root, find_repo_root

_DURATION = re.compile(r"^(\d+)([smhd]?)$")
_UNITS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> int:
    """Parse '90', '2m', '3h', '1d' into seconds."""
    match = _DURATION.match(text.strip())
    if not match:
        raise ValueError(f"invalid duration {text!r}; use e.g. 30m, 2h, 1d")
    return int(match.group(1)) * _UNITS[match.group(2)]


def _executable() -> str:
    """The absolute command Claude Code should run. Never a bare `readset`."""
    found = shutil.which("readset")
    if found:
        return str(Path(found).resolve())
    return f"{sys.executable} -m readset.cli"


def _agents(choice: str) -> list[Agent]:
    return list(AGENTS) if choice == "all" else [choice]  # type: ignore[list-item]


def _short(txn_id: str) -> str:
    """Shorten UUID-like ids for display; leave human-chosen ids alone."""
    return txn_id[:8] if len(txn_id) >= 32 and "-" in txn_id else txn_id


def _repo_root() -> Path:
    try:
        return find_repo_root(Path.cwd())
    except NotInRepoError:
        return Path.cwd()


def _require_ledger() -> Ledger | None:
    root = find_ledger_root(Path.cwd())
    if root is None:
        print("readset is not initialised here. Run: readset init", file=sys.stderr)
        return None
    return Ledger.open(root)


def cmd_init(args: argparse.Namespace) -> int:
    root = _repo_root()
    ledger = Ledger.open(root)
    save(root, Config(scope=args.scope))
    ignored = ensure_gitignore(root)
    print(paint("readset initialised", "green"))
    print(f"  ledger    {ledger.dir}")
    print(f"  scope     {args.scope}")
    for agent in _agents(args.agent):
        settings = settings_file(agent, root, user=args.user)
        changed = install_hooks(settings, _executable(), agent)
        state = "updated" if changed else "already installed"
        print(f"  {agent:9s} {settings} ({state})")
    if ignored:
        print(f"  gitignore added {LEDGER_DIR}/")
    print("\nOpen a second agent session on this repo and have both edit the same file.")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    root = _repo_root()
    removed = [
        agent
        for agent in _agents(args.agent)
        if remove_hooks(settings_file(agent, root, user=args.user))
    ]
    print(f"hooks removed for {', '.join(removed)}" if removed else "no readset hooks found")
    print(f"ledger left in place at {root / LEDGER_DIR}; delete it to remove all state")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    ledger = _require_ledger()
    if ledger is None:
        return 1
    live = ledger.live_transactions()
    if not live:
        print("no live transactions")
        return 0
    now = ledger.now()
    for info in live:
        short = _short(info.txn_id)
        label = short if not info.agent_type else f"{short} ({info.agent_type})"
        print(paint(label, "bold"), f"{info.kind}, started {human_age(now - info.started_at)}")
        for path, digest in ledger.begin(info.txn_id).read_set().items():
            print(f"  {path}  {digest[:12]}")
    return 0


def cmd_log(args: argparse.Namespace) -> int:
    ledger = _require_ledger()
    if ledger is None:
        return 1
    with ledger.connect() as conn:
        rows = conn.execute(
            "select * from conflict_log order by id desc limit ?", (args.limit,)
        ).fetchall()
    if not rows:
        print("no conflicts recorded")
        return 0
    now = ledger.now()
    for row in rows:
        head = (
            f"{row['path']}  {row['kind']}  txn {_short(row['txn_id'])}"
            f"  {human_age(now - row['detected_at'])}"
        )
        if row["changed_by"]:
            head += f"  changed by {_short(row['changed_by'])}"
        print(paint(head, "yellow"))
        if row["diff"]:
            print(row["diff"].rstrip("\n"))
        print()
    return 0


def cmd_gc(args: argparse.Namespace) -> int:
    ledger = _require_ledger()
    if ledger is None:
        return 1
    try:
        seconds = parse_duration(args.older_than)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    report = ledger.gc(older_than_seconds=seconds)
    print(f"ended {len(report.ended)} stale transaction(s), removed {report.blobs_removed} blob(s)")
    return 0


def cmd_demo(_: argparse.Namespace) -> int:
    from readset.demo import run

    code: int = run()
    return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="readset", description="Snapshot isolation for AI agents."
    )
    parser.add_argument("--version", action="version", version=f"readset {__version__}")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="initialise this repo and install Claude Code hooks")
    init.add_argument("--scope", choices=["strict", "hunk", "target"], default="hunk")
    init.add_argument("--agent", choices=[*AGENTS, "all"], default="claude")
    init.add_argument("--user", action="store_true", help="install into the user-level config")
    init.set_defaults(func=cmd_init)

    un = sub.add_parser("uninstall", help="remove the hooks readset installed")
    un.add_argument("--agent", choices=[*AGENTS, "all"], default="all")
    un.add_argument("--user", action="store_true")
    un.set_defaults(func=cmd_uninstall)

    status = sub.add_parser("status", help="live transactions and their read sets")
    status.set_defaults(func=cmd_status)

    log = sub.add_parser("log", help="conflicts caught, newest first")
    log.add_argument("--limit", type=int, default=20)
    log.set_defaults(func=cmd_log)

    gc = sub.add_parser("gc", help="end stale transactions and collect blobs")
    gc.add_argument("--older-than", default="24h")
    gc.set_defaults(func=cmd_gc)

    demo = sub.add_parser("demo", help="watch two agents collide, offline")
    demo.set_defaults(func=cmd_demo)

    hook = sub.add_parser("hook", help="hook entry point; reads an agent's payload on stdin")
    hook.add_argument("--agent", choices=AGENTS, default="claude")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "hook":
        if args.agent == "codex":
            return codex.main(sys.stdin, sys.stdout)
        return claude_code.main(sys.stdin, sys.stdout)
    if args.command is None:
        parser.print_help()
        return 0
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
