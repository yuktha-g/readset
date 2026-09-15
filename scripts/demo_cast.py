"""Turn `readset demo` output into an asciicast v2 file with readable timing.

The cast is rendered to docs/assets/demo.svg by `make demo-svg`. Generating it from the
real demo output (rather than screen-recording) keeps the animation reproducible.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time

from readset.demo import run

WIDTH, HEIGHT = 92, 30
LINE_DELAY = 0.28
PAUSE_AFTER = {"4.": 0.9, "What to do": 1.4, "5.": 0.9, "Without readset": 0.2}


def main() -> int:
    os.environ["FORCE_COLOR"] = "1"
    buf = io.StringIO()
    if run(buf) != 0:
        return 1
    events: list[list[object]] = []
    t = 0.6
    events.append([0.0, "o", "$ readset demo\r\n"])
    for line in buf.getvalue().splitlines():
        events.append([round(t, 2), "o", line + "\r\n"])
        t += LINE_DELAY
        for key, extra in PAUSE_AFTER.items():
            if line.strip().startswith(key):
                t += extra
    header = {
        "version": 2,
        "width": WIDTH,
        "height": HEIGHT,
        "timestamp": int(time.time()),
        "title": "readset demo",
    }
    out = sys.stdout
    out.write(json.dumps(header) + "\n")
    for event in events:
        out.write(json.dumps(event) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
