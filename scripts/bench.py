"""Measure hook overhead: p50/p95 wall time of `readset hook` for a Read and a validated Edit.

Each sample is a full subprocess, which is how Claude Code invokes the hook, so the
numbers include interpreter start-up. Run with: make bench
"""

from __future__ import annotations

import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from readset import __version__
from readset.ledger import Ledger

FILES = 1000
RUNS = 30


def _payload(repo: Path, event: str, tool: str, path: str) -> str:
    return json.dumps(
        {
            "session_id": "bench",
            "hook_event_name": event,
            "cwd": str(repo),
            "tool_name": tool,
            "tool_input": {"file_path": path},
            "tool_use_id": "toolu_bench",
        }
    )


def _time(payload: str) -> float:
    start = time.perf_counter()
    subprocess.run(
        [sys.executable, "-m", "readset.cli", "hook"],
        input=payload,
        capture_output=True,
        text=True,
        check=True,
    )
    return (time.perf_counter() - start) * 1000


def _percentile(samples: list[float], pct: float) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, round(pct * (len(ordered) - 1))))
    return ordered[index]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="readset-bench-") as tmp:
        repo = Path(tmp)
        for i in range(FILES):
            (repo / f"f{i}.py").write_text(f"x = {i}\n")
        ledger = Ledger.open(repo)
        txn = ledger.begin("bench", kind="session")
        for i in range(FILES):
            txn.record_read(f"f{i}.py")
        baseline = [
            _time(
                json.dumps({"session_id": "bench", "hook_event_name": "Notification", "cwd": tmp})
            )
            for _ in range(RUNS)
        ]
        reads = [_time(_payload(repo, "PostToolUse", "Read", "f1.py")) for _ in range(RUNS)]
        edits = [_time(_payload(repo, "PreToolUse", "Edit", "f1.py")) for _ in range(RUNS)]
    print(
        f"readset {__version__}, python {platform.python_version()}, {platform.system()}"
        f" {platform.machine()}, n={RUNS}, {FILES} tracked files"
    )
    rows = (
        ("interpreter start + no-op event", baseline),
        ("PostToolUse Read", reads),
        ("PreToolUse Edit, stale check", edits),
    )
    for name, samples in rows:
        print(
            f"{name:36s} p50 {statistics.median(samples):6.1f} ms"
            f"   p95 {_percentile(samples, 0.95):6.1f} ms"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
