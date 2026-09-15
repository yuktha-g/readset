# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
- CLI: `init`, `uninstall`, `status`, `log`, `gc`, `demo`, `hook`.
- Offline demo that needs no LLM.
- Zero runtime dependencies.
