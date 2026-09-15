"""`readset demo`: two agents collide on one file, offline, in a temp repo.

No LLM is involved. The point is to show exactly what an agent sees when readset
blocks a write, and that the fix is one re-read.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import IO

from readset._term import paint
from readset.ledger import Ledger
from readset.txn import Conflict

V1 = "TAX_RATE = 0.18\n\n\ndef total(net):\n    return net * (1 + TAX_RATE)\n"
V2 = "TAX_RATE = 0.20\n\n\ndef total(net):\n    return net * (1 + TAX_RATE)\n"
V_MERGED = "TAX_RATE = 0.20\n\n\ndef total(net):\n    return round(net * (1 + TAX_RATE), 2)\n"


def run(out: IO[str] | None = None) -> int:
    """Play the collision and print what each agent sees. Returns 0 on the expected outcome."""
    stream = out if out is not None else sys.stdout

    def say(text: str = "", colour: str | None = None) -> None:
        stream.write((paint(text, colour, stream=stream) if colour else text) + "\n")

    with tempfile.TemporaryDirectory(prefix="readset-demo-") as tmp:
        repo = Path(tmp)
        (repo / "billing.py").write_text(V1)
        ledger = Ledger.open(repo)
        a = ledger.begin("agent-a", kind="agent", agent_type="Refactor")
        b = ledger.begin("agent-b", kind="agent", agent_type="Fix")

        say("readset demo: two agents, one file, no locks", "bold")
        say()
        say("1. agent-a reads billing.py", "cyan")
        a.record_read("billing.py")
        say("2. agent-b reads billing.py", "cyan")
        b.record_read("billing.py")
        say("3. agent-b changes the tax rate and writes", "cyan")
        (repo / "billing.py").write_text(V2)
        b.record_write("billing.py")
        say("4. agent-a, still holding its old view, tries to write its refactor", "cyan")
        say()
        result = a.validate_write("billing.py")
        if not isinstance(result, Conflict):
            say("unexpected: write allowed", "red")
            return 1
        for line in result.message.splitlines():
            colour: str | None = None
            if line.startswith("-") and not line.startswith("---"):
                colour = "red"
            elif line.startswith("+") and not line.startswith("+++"):
                colour = "green"
            say("   " + line, colour)
        say()
        say("5. agent-a re-reads billing.py and retries against the current content", "cyan")
        a.record_read("billing.py")
        retry = a.validate_write("billing.py")
        if isinstance(retry, Conflict):
            say("unexpected: still blocked", "red")
            return 1
        (repo / "billing.py").write_text(V_MERGED)
        a.record_write("billing.py")
        say("   write succeeded; both changes are in the file", "green")
        say()
        say("Without readset, step 4 would have silently discarded agent-b's fix.", "dim")
    return 0
