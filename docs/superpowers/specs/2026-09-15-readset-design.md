# readset - design spec

Date: 2026-09-15. Status: approved for build (v0).

## One line

Snapshot isolation for AI agents. `readset` stops parallel coding agents from silently
overwriting each other, by validating every write against what the agent actually read.

## Why this exists

- AgenticFlict (AIware 2026, arXiv 2604.03551): 142k+ agent pull requests across 59k+ repos,
  27.67% merge-conflict rate, cross-agent pairs conflicting at about twice the rate of
  same-agent pairs.
- STORM (arXiv 2605.20563) names the unsolved primitive: "synchronisation alone does not
  provide transactional semantics or assumption-level consistency; one agent may plan from an
  old repository snapshot, another may test a newer patch, and a third may remember an
  obsolete invariant."
- Databases solved this in the 1980s: optimistic concurrency control with read-set validation.
  Nobody has ported it to agents. `readset` is that port.

The most common real-world collision is not subagents. It is two or three Claude Code
terminals open on the same repo. The README leads with that.

## Non-negotiable product rules

1. **Fail-open.** Any exception inside the hook path is logged to `.readset/errors.log` and the
   tool call is allowed. A guard that ever bricks a user's session is dead on arrival.
2. **Zero runtime dependencies.** Stdlib only (`sqlite3`, `hashlib`, `difflib`, `json`,
   `argparse`). This is what makes a hook that runs on every file edit trustworthy, and what
   makes the core embeddable by frameworks. (This deliberately overrides the Pydantic Settings
   standard used in Stylumia work projects; the reason is the zero-dep product decision.)
3. **No daemon.** Every hook invocation is a short-lived process against SQLite in WAL mode.
4. **The demo needs no LLM.** `readset demo` simulates a two-agent collision in-process,
   offline, deterministically. It is the README screenshot.
5. **Hooks are installed with the absolute executable path**, never bare `readset`, because
   PATH differences inside Claude Code's hook shell are the first support ticket every
   hook-based tool gets.
6. Python >= 3.10. MIT licence. `uv` toolchain, Makefile-only commands.

## Scope

**v0 (this week)**

- State model: files in one git repository. Paths stored relative to the repo root.
- Topology: several agents editing the same working directory concurrently.
- Integration: Claude Code hooks. Transaction identity is `agent_id` when present (subagent),
  else `session_id`.
- Conflict rule: block the write and hand the agent the diff. No auto-merge.
- Validation scope: `readset` (whole read set) by default; `target` (only the written file)
  as an option.

**Explicitly out of v0**

- Separate git worktrees and merge-time validation.
- Generic key-value state (non-file).
- Codex, Cursor, LangGraph, CrewAI adapters. The core API is designed so these are thin.
- Hunk-level read sets (v0 is whole-file). Auto-merge of non-overlapping hunks.
- Recording `Grep`/`Glob` output as reads. Only `Read` and `NotebookEdit` reads count.
- Full serialisability. v0 prevents lost updates and writes based on stale reads; write-skew
  across files neither agent wrote is possible, the same trade Postgres makes at
  `REPEATABLE READ`.

## Architecture

```
src/readset/
  __init__.py        public API: Ledger, Transaction, Conflict, Ok, __version__
  paths.py           repo-root discovery, path normalisation, ignore rules
  hashing.py         sha256 of file bytes; ABSENT sentinel for missing files
  ledger.py          SQLite schema, connection handling (WAL), blob store
  txn.py             the primitive: begin / record_read / validate_write / record_write / end
  diff.py            unified diff between blob and disk, truncation, attribution text
  config.py          .readset/config.json load/save with defaults
  hooks/
    __init__.py
    claude_code.py   stdin JSON -> action -> stdout JSON. Fail-open wrapper lives here.
  cli.py             argparse: init, uninstall, status, log, demo, gc, hook, --version
  demo.py            the in-process two-agent collision
  _term.py           minimal ANSI colour helpers (no rich)
```

Layering rule: `txn.py`, `ledger.py`, `diff.py`, `hashing.py`, `paths.py` never import from
`hooks/`, `cli.py` or `demo.py`. The adapter is replaceable; the core is the product.

## Ledger schema

SQLite at `<repo>/.readset/ledger.db`, WAL mode, `busy_timeout` 2000 ms.

```sql
CREATE TABLE txn (
  txn_id      TEXT PRIMARY KEY,
  kind        TEXT NOT NULL,            -- 'session' | 'agent' | 'library'
  parent_txn  TEXT,
  agent_type  TEXT,
  started_at  REAL NOT NULL,
  ended_at    REAL
);
CREATE TABLE read_set (
  txn_id  TEXT NOT NULL,
  path    TEXT NOT NULL,
  hash    TEXT NOT NULL,                -- sha256 hex, or 'absent'
  seen_at REAL NOT NULL,
  PRIMARY KEY (txn_id, path)
);
CREATE TABLE write_log (
  id          INTEGER PRIMARY KEY,
  txn_id      TEXT NOT NULL,
  path        TEXT NOT NULL,
  old_hash    TEXT,
  new_hash    TEXT NOT NULL,
  tool_use_id TEXT,
  written_at  REAL NOT NULL
);
CREATE TABLE conflict_log (
  id            INTEGER PRIMARY KEY,
  txn_id        TEXT NOT NULL,
  path          TEXT NOT NULL,
  expected_hash TEXT NOT NULL,
  actual_hash   TEXT NOT NULL,
  changed_by    TEXT,                   -- txn_id that produced actual_hash, if known
  diff          TEXT NOT NULL,
  tool_use_id   TEXT,
  detected_at   REAL NOT NULL
);
```

Blob store: `.readset/objects/<sha256>` holds the bytes of every file version a live transaction
has observed. This is what makes a real diff possible. Blobs unreferenced by any live
transaction's `read_set` are removed by `gc`.

## Transaction semantics

- **record_read(path).** Hash disk content, store blob, upsert `read_set[txn, path]`. Missing
  file records `absent`.
- **validate_write(path, scope).**
  - No entry and file exists on disk: `Conflict(kind="blind_overwrite")`. Blind overwrite of
    a file never read is the textbook lost update.
  - No entry and file absent: `Ok`. It is a creation. Two agents creating the same file: the
    second finds it exists and never read it, and is blocked. Correct.
  - Entry present, hash equals disk: `Ok` for this path.
  - Entry present, hash differs: `Conflict(kind="stale_read")` with the diff between the blob
    the agent saw and disk, plus `changed_by` from `write_log` where `new_hash` equals the
    current disk hash.
  - `scope="readset"`: additionally check every other entry in this transaction's read set;
    any that differ from disk are listed as `stale_paths`, and the write is blocked even when
    the target file itself is unchanged.
- **record_write(path, tool_use_id).** Rehash disk, store blob, update this transaction's
  `read_set` entry to the new hash, append `write_log`. An agent never conflicts with its own
  write.
- **begin / end.** `end` sets `ended_at`. On `end` of a subagent transaction, each path in the
  child's `write_log` is folded into the parent's `read_set` at the child's final hash, so the
  parent sees its child's results without a spurious conflict. This is the one deliberate
  departure from strict isolation.
- **Bash heuristic.** After a `Bash` tool call, any read-set entry whose relative path appears
  as a substring of the command is refreshed to the current disk hash and treated as this
  transaction's own write. Handles `sed -i` and friends. Documented as a heuristic.
- **Stale transactions.** Sessions that never emit `SessionEnd` remain open. `readset status` shows
  them with age; `readset gc --older-than 24h` ends them and collects blobs.

## Claude Code hook contract

`readset init` writes these entries into `.claude/settings.json` (project scope by default;
`--user` targets `~/.claude/settings.json`), each tagged with `"_readset": true` so
`uninstall` removes exactly what `init` added and `init` is idempotent:

| Event | Matcher | Action |
|---|---|---|
| `PreToolUse` | `Edit\|Write\|MultiEdit\|NotebookEdit` | `validate_write`; on conflict print deny JSON |
| `PostToolUse` | `Read\|NotebookEdit\|Edit\|Write\|MultiEdit\|Bash` | `record_read` / `record_write` / Bash heuristic |
| `SubagentStart` | `*` | `begin(agent_id, kind="agent", parent=session_id)` |
| `SubagentStop` | `*` | `end(agent_id)` with fold-into-parent |
| `SessionStart` | `*` | `begin(session_id, kind="session")` |
| `SessionEnd` | `*` | `end(session_id)` |

Hook command: `"<absolute path to readset> hook"`. Input is the hook JSON on stdin.

Path fields per tool: `Read.file_path`, `Edit.file_path`, `Write.file_path`,
`MultiEdit.file_path`, `NotebookEdit.notebook_path`. `Read` is recorded on `PostToolUse` so
a failed read records nothing.

Transaction identity: `agent_id` if present in the payload, else `session_id`. A session
transaction is begun on `SessionStart`, or implicitly on the first event carrying an unseen `session_id`,
and ended on `SessionEnd`. `Stop` is deliberately not used: it fires after every assistant turn,
and read sets must survive across turns.

Block output (exit 0, stdout):

```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse",
  "permissionDecision": "deny",
  "permissionDecisionReason": "<conflict message>"}}
```

Conflict message shown to the agent:

```
readset: write to src/auth.py blocked - the file changed after you read it.

Changed by: agent 7f3a (Explore), 40s ago
--- what you read (14:01:31)
+++ what is on disk now (14:02:11)
@@ -10,3 +10,4 @@
 def login(user):
-    return check(user)
+    if not user.active:
+        raise Inactive(user)
+    return check(user)

Also stale in your read set: src/models.py

What to do: Read the file(s) above again, then retry your edit against the current content.
```

Diff is capped at `diff_max_lines` (default 200) with a truncation note.

## Library API

```python
from readset import Ledger

ledger = Ledger.open("/path/to/repo")            # creates .readset/ if needed
txn = ledger.begin("agent-a", kind="library")
txn.record_read("src/auth.py")
result = txn.validate_write("src/auth.py")       # Ok | Conflict
if result.ok:
    ...  # perform the write
    txn.record_write("src/auth.py")
else:
    print(result.message)                        # the same text the hook shows an agent
txn.end()
```

`Conflict` fields: `path`, `kind` (`stale_read` | `blind_overwrite`), `expected_hash`,
`actual_hash`, `diff`, `changed_by`, `stale_paths`, `message`. `Ok` has `ok = True`.

## CLI

```
readset init [--scope readset|target] [--user]   install hooks, create .readset/, gitignore it
readset uninstall [--user]                       remove exactly the hooks init added
readset status                                   live transactions, their read sets, stale ones
readset log [--limit N]                          conflicts caught, with diffs
readset demo                                     the offline two-agent collision
readset gc [--older-than 24h]                    end stale transactions, collect blobs
readset hook                                     hook entry point; reads stdin JSON
readset --version
```

Config: `.readset/config.json` with `{"scope": "readset", "diff_max_lines": 200,
"ignore": [".readset/**", ".git/**"]}`.

## Demo

`readset demo` runs, in-process, against a temp repo:

1. Agent A reads `billing.py`.
2. Agent B reads `billing.py`, edits the tax rate, writes.
3. Agent A tries to write `billing.py` with its stale view.
4. `readset` blocks A and prints the conflict message with the diff and "Changed by: agent B".
5. A re-reads, retries, succeeds.

Output is coloured, deterministic, and fits one terminal screen.

## Testing

Tests are named `test_should_<behaviour>_when_<condition>`. `pytest` only, run via
`make test`. `uv` manages the venv; `ruff` via `uvx` for lint.

Unit (`tests/unit/`), all against temp directories, no subprocesses:
- hashing: identical bytes hash identical; missing file yields `absent`.
- ledger: schema created once; concurrent connections do not corrupt (WAL); blob round-trip.
- txn: each rule above has at least one test - blind overwrite blocked, creation allowed,
  matching hash allowed, stale read blocked with diff, own write never conflicts, scope
  `readset` blocks on stale sibling, scope `target` ignores stale sibling, subagent end folds
  into parent, Bash heuristic refreshes mentioned paths only, `changed_by` attribution.
- diff: truncation at `diff_max_lines`; binary files produce a "binary, N bytes" note.
- claude_code adapter as a pure function `dispatch(payload) -> HookResult`: every event and
  tool mapping; identity from `agent_id` vs `session_id`; unknown tool is a no-op.
- cli init/uninstall: idempotent; merges into existing settings without touching other
  hooks; writes absolute executable path.

Integration (`tests/integration/`): invoke `readset hook` as a subprocess with a realistic
sequence of stdin payloads in a temp repo, assert the deny JSON on conflict; corrupt the ledger
and assert fail-open (exit 0, no JSON, error logged).

## Build order (one week)

1. Skeleton, `pyproject.toml`, Makefile, hashing, paths, ledger. Tests green.
2. `txn.py` rules, `diff.py`, attribution, scopes, lifecycle fold. Tests green.
3. Claude Code adapter, fail-open wrapper, integration tests.
4. CLI: init/uninstall/status/log/gc.
5. `demo`, README with the demo output, docs.
6. Dogfood with real parallel Claude Code sessions on this repo; fix what breaks.
7. Launch prep: GIF, post, publish under the user's GitHub account and PyPI.

## Risks, stated

- Whole-file granularity means unrelated edits to one file conflict. Correct but noisy; hunk
  level is v0.2.
- `readset` scope may interrupt more than users expect. The remedy is always one re-read, and
  the message says so. `target` scope exists for people who want quiet.
- Adoption of a primitive needs a framework to embed it; that is advocacy after the week, not
  code during it.

## Quality bar (production-grade, not a weekend script)

- Full type annotations; `mypy --strict` passes on `src/`.
- `ruff check` and `ruff format --check` clean; configured in `pyproject.toml`.
- `pytest --cov=readset` with a coverage floor of 90% enforced in CI.
- GitHub Actions workflow: matrix over Python 3.10, 3.11, 3.12, 3.13 on Linux and macOS,
  running lint, types, tests. Publish workflow to PyPI on tag via trusted publishing.
- `make bench` measures hook overhead (p50/p95 wall time for `readset hook` on a Read and on a
  validated Write against a repo with 1,000 tracked files). The numbers go in the README with
  the command that produced them.
- Every public function has a docstring stating what it does, what it returns, and what it
  raises. Errors are typed (`ReadsetError` hierarchy), never bare exceptions.
- `CHANGELOG.md` (Keep a Changelog), `CONTRIBUTING.md`, `LICENSE` (MIT), `SECURITY.md`.
- README: problem in two sentences, the demo output, install, how it works (with the
  isolation guarantee stated precisely), limitations, roadmap, prior art and citations.

## Addendum 2026-09-15: worktree merge validation (`readset merge-check`)

**Problem.** Teams isolate agents in git worktrees and only discover collisions as conflict
markers at merge time. Worse, git merges *adjacent* hunks silently, and it never notices when
a branch relied on a file the other side changed but the branch did not touch (write skew).

**Command.** `readset merge-check [--into <branch>] [--margin N] [--strict] [--json]`, run
inside a worktree or branch checkout. Exit 0 when safe, 1 when a conflict is found, 2 on
usage errors. Library entry point: `readset.merge.merge_check(root, into) -> MergeReport`.

**Algorithm.**
1. `base = git merge-base HEAD <into>`. `<into>` defaults to `origin/HEAD`'s branch, else `main`.
2. `ours` = paths that differ between `base` and the working tree (committed or not).
3. `theirs` = paths that differ between `base` and `<into>`.
4. `read` = every path in this checkout's ledger read sets and write log (all transactions).
5. For each path in `theirs`:
   - in `ours`: compute both sides' changed line ranges in base coordinates
     (`hunks.changed_ranges`); any pair within `margin` lines is an **overlap conflict**.
     Disjoint ranges are a **both-changed notice** (git will merge them; review).
   - not in `ours` but in `read`: a **stale dependency** notice, or a conflict with `--strict`.
   - otherwise ignored.
6. Report per path with kind, both ranges, and their diff (capped by `diff_max_lines`).

**Working tree vs HEAD.** Normally "ours" is the working tree diffed against `base`, so
uncommitted local edits count. But `git merge` applies non-conflicting changes to the
working tree and index *before* invoking `pre-merge-commit` - by that point the tree already
mixes both sides. `merge_check` detects an in-progress merge (`MERGE_HEAD` exists) and reads
`HEAD` instead of the working tree in that case, since HEAD has not moved yet and is the
only trustworthy source of "ours" during the hook. Found via a real false-positive overlap
while building the `pre-merge-commit` hook: a disjoint edit was reported as overlapping
because the working tree, mid-merge, already contained the other side's change too.

**Why the base snapshot is the read snapshot.** A worktree created from `base` observed
every file at `base`; that is exactly a read set with `base` as the content. The ledger adds
the files the agent actually looked at, which is what makes the stale-dependency notice possible.

**Out of scope.** Rewriting the merge, three-way content merging, and hooking `git merge`
itself. `merge-check` is a gate a human or CI runs before merging; a git `pre-merge-commit`
hook can call it.
