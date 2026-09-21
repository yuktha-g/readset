# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-09-21

### Added

- A GitHub composite Action (`action.yml`) that runs `merge-check` as a required PR check:
  `uses: yuktha-g/readset@v0.2.0`. Distinguishes a real conflict (exit 1, blocks the PR
  with the diff) from a tool error such as an unresolvable target ref (exit 2, fails the
  step with a clear message instead of a JSON-parse crash). Verified end to end against a
  real GitHub Actions runner: a trivially-clean check reporting `ok=true`, and an
  unresolvable ref correctly failing the step - see `.github/workflows/readset.yml`, which
  runs this action on readset's own PRs.
- A documented GitLab CI job template (`docs/ci/gitlab-ci.yml`) for the same check on merge
  requests. Not live-tested against a real GitLab runner.

## [0.1.0] - 2026-09-15

### Added

- Transaction core: per-agent read sets, write validation against disk, blind-overwrite
  detection, stale-read detection with a real diff, attribution of the change to the
  transaction that made it.
- Three validation scopes: `hunk` (default: an edit is blocked only if it overlaps a change
  the agent has not seen; other staleness is injected as context), `strict` (any stale entry
  in the read set blocks) and `target` (only the written file, as a whole).
- A transaction's view after an allowed edit is what it read plus its own edits, never
  the disk, so unseen changes stay protected.
- Subagent transactions fold their writes into the parent's read set when they end.
- Bash heuristic: read-set paths named in a `Bash` command are refreshed as own writes.
- Claude Code adapter via hooks, fail-open, with `agent_id` / `session_id` identity.
- Codex CLI adapter: `apply_patch` parsed into per-file edits, reads inferred from shell
  commands, `readset init --agent codex`.
- Multi-process contention test (16 workers, 3,200 ops) and a fix for a blob-store race it
  found.
- CLI: `init`, `uninstall`, `status`, `log`, `gc`, `demo`, `hook`.
- Claude Code plugin manifest: `claude plugin install readset@readset`, runs from source,
  auto-initialises the ledger at the git root via `.git/info/exclude`.
- `readset install-git-hook` / `uninstall-git-hook`: run `merge-check` automatically via a
  `prepare-commit-msg` hook before every merge commit.
- `readset merge-check`: validate a worktree or branch against its target before merging,
  with hunk-level overlap blocking and stale-dependency notes from the ledger.
- `readset doctor` for install diagnosis; `readset log --json`; bounded `errors.log` with
  event context per entry.
- Offline demo that needs no LLM.
- Zero runtime dependencies.
