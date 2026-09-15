# Contributing

Thanks for looking. readset is small on purpose; contributions that keep it small are the
most welcome kind.

## Setup

```
make setup      # uv sync with the dev group
make check      # ruff, mypy --strict, pytest with coverage
make demo       # the offline collision
make bench      # hook latency
```

Python 3.10 or newer. `uv` is the only tool you need installed.

## Rules of the house

- **Zero runtime dependencies.** The core is stdlib only. A PR that adds a dependency
  needs a reason that beats "trustworthy hook that runs on every file edit".
- **Fail-open in the hook path.** Nothing under `readset/hooks/` may let an exception reach
  Claude Code. Log it and allow the tool call.
- **Layering.** `paths`, `hashing`, `ledger`, `txn`, `diff`, `config`, `errors` never import
  from `hooks/`, `cli` or `demo`. The core is the product; adapters are replaceable.
- **Tests are named `test_should_<behaviour>_when_<condition>`** and live under
  `tests/unit/` (no subprocesses) or `tests/integration/` (subprocesses allowed).
- **`mypy --strict` and `ruff` must be clean.** CI enforces it on four Python versions and
  two operating systems.
- Hyphens, not em dashes, in code, comments and docs.

## Adding an adapter

An adapter maps one framework's events onto four calls: `Transaction.record_read`,
`Transaction.validate_write`, `Transaction.record_write`, `Transaction.end`. Look at
`readset/hooks/claude_code.py`; it is under 150 lines and that is the target for any
new one. Open an issue first so we agree on the identity model (what is "one agent" in
your framework).

## Reporting a bug

Include the output of `readset status`, `readset log`, and the tail of
`.readset/errors.log` if it exists. Those three usually make the bug reproducible.
