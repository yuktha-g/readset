"""Many transactions in separate processes against one ledger.

Each worker loops: read a shared counter file, validate the write, bump the counter,
record the write. A per-file OS lock wraps validate-write-record so the test isolates the
ledger's behaviour from the tool-execution race that is outside readset's control.
Expectations: no exceptions from SQLite under contention, real conflicts observed, and the
ledger reconciling exactly with the files on disk.
"""

from __future__ import annotations

import fcntl
import multiprocessing as mp
import random
from pathlib import Path

from readset.ledger import Ledger
from readset.txn import Conflict

WORKERS = 8
ROUNDS = 40
FILES = 5


def _worker(root: str, worker_id: int, rounds: int, out: mp.Queue) -> None:  # type: ignore[type-arg]
    ledger = Ledger.open(root)
    txn = ledger.begin(f"w{worker_id}", kind="agent", agent_type="stress")
    rng = random.Random(worker_id)
    ok = conflicts = errors = 0
    try:
        for path in (f"c{i}.txt" for i in range(FILES)):
            txn.record_read(path)
        for _ in range(rounds):
            path = f"c{rng.randrange(FILES)}.txt"
            lock_path = Path(root) / ".readset" / f"{path}.lock"
            with lock_path.open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = txn.validate_write(path, scope="target")
                if isinstance(result, Conflict):
                    conflicts += 1
                    txn.record_read(path)
                    continue
                target = Path(root) / path
                target.write_text(str(int(target.read_text()) + 1))
                txn.record_write(path)
                ok += 1
    except Exception as exc:  # pragma: no cover - reported through the queue
        errors += 1
        out.put(("error", worker_id, repr(exc)))
    out.put(("done", worker_id, ok, conflicts, errors))


def test_should_stay_consistent_when_many_processes_write_concurrently(repo: Path) -> None:
    for i in range(FILES):
        (repo / f"c{i}.txt").write_text("0")
    Ledger.open(repo)
    ctx = mp.get_context("spawn")
    queue: mp.Queue = ctx.Queue()  # type: ignore[type-arg]
    procs = [
        ctx.Process(target=_worker, args=(str(repo), w, ROUNDS, queue)) for w in range(WORKERS)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
    results = [queue.get(timeout=5) for _ in range(WORKERS)]

    errors = [r for r in results if r[0] == "error"]
    assert errors == [], errors
    total_ok = sum(r[2] for r in results)
    total_conflicts = sum(r[3] for r in results)
    assert total_ok + total_conflicts == WORKERS * ROUNDS
    assert total_conflicts > 0, "no contention observed; the test is not exercising anything"

    on_disk = sum(int((repo / f"c{i}.txt").read_text()) for i in range(FILES))
    assert on_disk == total_ok, "an increment was lost or double counted"

    ledger = Ledger.open(repo)
    with ledger.connect() as conn:
        writes = conn.execute("select count(*) from write_log").fetchone()[0]
        logged_conflicts = conn.execute("select count(*) from conflict_log").fetchone()[0]
        referenced = {r[0] for r in conn.execute("select hash from read_set")}
    assert writes == total_ok
    assert logged_conflicts == total_conflicts
    for digest in referenced:
        assert (ledger.objects_dir / digest).exists(), f"blob {digest} missing"
