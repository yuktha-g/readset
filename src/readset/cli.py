"""Command-line interface. `readset hook` is the entry point Claude Code calls."""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import shutil
import sys
from pathlib import Path

from readset import __version__
from readset._term import paint
from readset.config import Config, save
from readset.config import load as load_config
from readset.diff import human_age
from readset.errors import NotInRepoError
from readset.hooks import claude_code, codex
from readset.hooks._runner import ERROR_LOG
from readset.install import (
    AGENTS,
    Agent,
    ensure_gitignore,
    install_hooks,
    is_readset_hook,
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
    if args.json:
        print(json.dumps([dict(row) for row in rows], indent=2))
        return 0
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


def _plugin_installed() -> bool:
    """True if the readset Claude Code plugin is installed for this user."""
    path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    plugins = data.get("plugins", {}) if isinstance(data, dict) else {}
    return isinstance(plugins, dict) and any(k.startswith("readset@") for k in plugins)


def _hooks_present(path: Path) -> bool:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return False
    hooks = data.get("hooks") if isinstance(data, dict) else None
    if not isinstance(hooks, dict):
        return False
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            handlers = group.get("hooks", []) if isinstance(group, dict) else []
            if any(isinstance(h, dict) and is_readset_hook(h) for h in handlers):
                return True
    return False


def cmd_doctor(_: argparse.Namespace) -> int:
    """Check the things that make readset silently do nothing, and print a paste-able report."""
    ok = True

    def line(name: str, good: bool, detail: str) -> None:
        nonlocal ok
        ok = ok and good
        mark = paint("ok", "green") if good else paint("FAIL", "red")
        print(f"  {name:16s} {mark:4s}  {detail}")

    print(paint(f"readset {__version__} doctor", "bold"))
    py = sys.version_info
    line("python", py >= (3, 10), f"{py.major}.{py.minor}.{py.micro} at {sys.executable}")

    root = find_ledger_root(Path.cwd())
    if root is None:
        line("ledger", False, "not initialised here; run `readset init` or install the plugin")
        print(paint("\nsome checks failed", "red"))
        return 1
    try:
        ledger = Ledger.open(root)
        live = ledger.live_transactions()
        line("ledger", True, f"{ledger.db_path} ({len(live)} live transaction(s))")
    except Exception as exc:  # the whole point of doctor is to surface this
        line("ledger", False, f"{root / LEDGER_DIR / 'ledger.db'}: {type(exc).__name__}: {exc}")
        ledger = None

    cfg = load_config(root)
    line("config", True, f"scope={cfg.scope} hunk_margin={cfg.hunk_margin}")

    plugin = _plugin_installed()
    found = []
    for agent in AGENTS:
        for user in (False, True):
            path = settings_file(agent, root, user=user)
            if _hooks_present(path):
                found.append(f"{agent}: {path}")
    if plugin:
        line("hooks (claude)", True, "installed via the readset plugin")
    elif any(f.startswith("claude") for f in found):
        line("hooks (claude)", True, next(f for f in found if f.startswith("claude")))
    else:
        line(
            "hooks (claude)",
            False,
            "no readset hooks found; run `readset init` or install the plugin",
        )
    codex = [f for f in found if f.startswith("codex")]
    if codex:
        line("hooks (codex)", True, codex[0])

    errors = root / LEDGER_DIR / ERROR_LOG
    if errors.exists() and errors.stat().st_size > 0:
        tail = errors.read_text().rstrip("\n").splitlines()[-8:]
        line("errors.log", False, f"{errors} ({errors.stat().st_size} bytes); last lines:")
        for entry in tail:
            print("        " + entry)
    else:
        line("errors.log", True, "empty")

    if ledger is not None:
        with ledger.connect() as conn:
            conflicts = conn.execute("select count(*) from conflict_log").fetchone()[0]
        print(f"  {'conflicts':16s} {'':4s}  {conflicts} caught so far in this repo")

    print(paint("\nall checks passed", "green") if ok else paint("\nsome checks failed", "red"))
    return 0 if ok else 1


def cmd_merge_check(args: argparse.Namespace) -> int:
    """Validate this checkout against the target branch before merging."""
    from readset.merge import GitError, default_target, merge_check

    root = Path.cwd()
    try:
        root = find_repo_root(root)
    except NotInRepoError:
        print("not inside a git repository", file=sys.stderr)
        return 2
    into = args.into or default_target(root)
    cfg = load_config(root)
    try:
        report = merge_check(
            root,
            into=into,
            margin=args.margin if args.margin is not None else cfg.hunk_margin,
            strict=args.strict,
            diff_max_lines=cfg.diff_max_lines,
        )
    except GitError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        payload = {
            "into": report.into,
            "base": report.base,
            "ok": report.ok,
            "findings": [dataclasses.asdict(f) for f in report.findings],
        }
        print(json.dumps(payload, indent=2))
        return 0 if report.ok else 1
    print(paint(f"readset merge-check: HEAD into {into} (base {report.base[:10]})", "bold"))
    if not report.findings:
        print(paint("  clean: nothing changed on both sides", "green"))
        return 0
    margin = args.margin if args.margin is not None else cfg.hunk_margin
    for f in report.findings:
        if f.kind == "overlap":
            print(paint(f"  {f.path}: BLOCK - both sides edited within {margin} lines", "red"))
            print(f"      ours {f.ours}  theirs {f.theirs}")
        elif f.kind == "both_changed":
            print(paint(f"  {f.path}: note - both sides changed, disjoint regions", "yellow"))
            print(f"      ours {f.ours}  theirs {f.theirs}")
        else:
            mark = "BLOCK" if f.blocking else "note"
            print(paint(f"  {f.path}: {mark} - you read this file and {into} changed it", "yellow"))
        if f.diff and (f.blocking or args.verbose):
            for line in f.diff.rstrip("\n").splitlines():
                print("      " + line)
    if report.ok:
        print(paint("\nsafe to merge; review the notes above", "green"))
        return 0
    print(paint("\nnot safe to merge: rebase onto " + into + " and re-run", "red"))
    return 1


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
    log.add_argument("--json", action="store_true", help="machine-readable output")
    log.set_defaults(func=cmd_log)

    gc = sub.add_parser("gc", help="end stale transactions and collect blobs")
    gc.add_argument("--older-than", default="24h")
    gc.set_defaults(func=cmd_gc)

    mc = sub.add_parser(
        "merge-check", help="validate this branch against its target before merging"
    )
    mc.add_argument("--into", default=None, help="target branch (default: origin/HEAD or main)")
    mc.add_argument("--margin", type=int, default=None, help="lines of separation required")
    mc.add_argument("--strict", action="store_true", help="stale dependencies block too")
    mc.add_argument("--verbose", action="store_true", help="show diffs for notes as well")
    mc.add_argument("--json", action="store_true")
    mc.set_defaults(func=cmd_merge_check)

    doctor = sub.add_parser("doctor", help="check the install and print a paste-able report")
    doctor.set_defaults(func=cmd_doctor)

    demo = sub.add_parser("demo", help="watch two agents collide, offline")
    demo.set_defaults(func=cmd_demo)

    hook = sub.add_parser("hook", help="hook entry point; reads an agent's payload on stdin")
    hook.add_argument("--agent", choices=AGENTS, default="claude")
    hook.add_argument(
        "--auto-init",
        action="store_true",
        help="on SessionStart, create the ledger at the git root if missing (plugin mode)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "hook":
        if args.agent == "codex":
            return codex.main(sys.stdin, sys.stdout)
        return claude_code.main(sys.stdin, sys.stdout, auto_init=args.auto_init)
    if args.command is None:
        parser.print_help()
        return 0
    result: int = args.func(args)
    return result


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
