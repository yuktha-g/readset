# Security

## What readset stores

readset keeps a copy of every file version a live transaction has observed, under
`<repo>/.readset/objects/`, so that a blocked write can show a real diff. This directory
is added to `.gitignore` by `readset init` and never leaves your machine. `readset gc`
removes copies no live transaction references.

readset never sends anything over the network and has no runtime dependencies.

## What readset can and cannot do to your session

The hook is fail-open: any internal error is written to `.readset/errors.log` and the
tool call is allowed. readset can block a write; it cannot modify one, run commands, or
read files outside the repository root.

## Reporting a vulnerability

Please report privately by email to the maintainer listed in `pyproject.toml` rather
than in a public issue. You will get an acknowledgement within a few days.
