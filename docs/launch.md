# Launch material

Everything below states only what the repo can prove. Numbers come from `make bench`,
`tests/integration/test_concurrency.py`, and the cited papers.

## Hacker News: Show HN

**Title:** Show HN: readset - snapshot isolation for AI coding agents (stops parallel agents
overwriting each other)

**Body:**

I run two or three Claude Code sessions on the same repo, and sometimes subagents on top.
Every so often one of them wrote a file from a stale copy and quietly deleted another one's
work. No error, no conflict marker, just a change that vanished.

This turns out to be common. AgenticFlict (AIware 2026) measured 142k+ agent PRs across 59k+
repos: a 27.67% conflict rate, with cross-agent pairs conflicting at about twice the rate of a
single agent's own work. Git worktrees defer the collision to merge time; they don't prevent it.

Databases solved this in the 1980s with optimistic concurrency control: a transaction records
what it read, and a write is rejected if any of that changed underneath it. readset is that
idea, ported to agents.

How it works: every agent session is a transaction. Claude Code hooks record each Read into
the session's read set (with a copy of the content). Before each Edit or Write, readset checks
the read set against disk. If the file changed since you read it and your edit overlaps the
change, the write is blocked and the agent gets a unified diff plus who changed it. It re-reads
and retries. If the change is elsewhere in the file (or in another file you read), the edit
goes through and the diff is injected as context instead, so the agent knows without being
stopped.

The part I'm most pleased with: after an allowed edit, the transaction's view of the file is
"what it read plus its own edit", not what's on disk. So the diff between its view and disk is
always exactly what other agents changed, and the next edit to that region is still caught.
Nothing is silently inherited.

Facts:

- Zero runtime dependencies (stdlib only). No daemon. Hook overhead is ~1 ms for a read and
  ~23 ms to validate a 1,000-file read set, plus Python start-up.
- Fail-open: any internal error is logged and the tool call proceeds. A guard that can break
  your session is worse than no guard.
- Contention test: 16 processes, 3,200 operations, 2,456 conflicts caught, 0 errors, every
  increment accounted for on disk. It found a real race in my blob store before anyone else did.
- Install as a Claude Code plugin (`claude plugin install readset@readset`) and it runs from
  source with any python3 >= 3.10, initialising itself in any git repo you open. Or
  `uv tool install readset && readset init` per repo.
- A Codex CLI adapter is included (parses `apply_patch` into per-file edits); it is
  unit-tested against the documented payloads but not yet run against a live Codex install.
- `readset demo` shows the whole thing offline in ten seconds, no LLM needed.

What it doesn't do: full serialisability (two agents can still write-skew across regions
neither wrote, the same trade Postgres makes at REPEATABLE READ), worktree merge validation,
or three-way merges for whole-file writes.

Repo: <link>. MIT.

## X / LinkedIn thread

1/ Two Claude Code sessions on one repo. Agent A reads billing.py. Agent B fixes the tax rate.
Agent A writes its refactor from the old copy. B's fix is gone. No error. Nobody noticed.

2/ AgenticFlict measured 142k agent PRs: 27.67% conflict rate. Worktrees just move the crash
to merge time.

3/ Databases fixed this in 1981. Optimistic concurrency control: record what you read, reject
the write if it changed. Nobody had ported it to agents. So I did.

4/ readset: every agent session is a transaction. Claude Code hooks track reads. Before every
edit, the read set is checked against disk. Overlapping change: blocked, with a diff and who
did it. Change elsewhere: allowed, with the diff injected as context.

5/ Zero dependencies. No daemon. ~1 ms per read. Fail-open, so it can never break your session.
16-process stress test: 3,200 ops, 2,456 conflicts caught, 0 errors, 0 lost updates.

6/ `claude plugin install readset@readset` and it just works in every git repo you open. Or
`readset demo` to watch two agents collide offline. Repo: <link>

## Reddit (r/ClaudeAI, r/LocalLLaMA)

Title: I built snapshot isolation for parallel Claude Code sessions so they stop overwriting
each other (zero deps, one-command plugin install)

Body: the Show HN text, minus the first paragraph, plus the demo SVG.

## Before posting

- [ ] Replace `yuktha-g/readset` in `pyproject.toml`, `.claude-plugin/*.json` and README with
      the real GitHub path.
- [ ] Push, confirm CI is green on all 8 matrix cells.
- [ ] Tag `v0.1.0`, confirm the PyPI publish workflow succeeds (trusted publisher must be
      configured on PyPI first: project `readset`, owner `<github user>`, repo `readset`,
      workflow `publish.yml`, environment `pypi`).
- [ ] `uv tool install readset` from PyPI on a clean machine, run `readset demo`.
- [ ] `claude plugin marketplace add <user>/readset && claude plugin install readset@readset`
      on a clean machine.
- [ ] Post HN first thing on a weekday morning US time. Reply to every comment for 6 hours.
