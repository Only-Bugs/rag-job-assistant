"""Summarize stage medians from logs/runtime.log."""

from __future__ import annotations

import re
import statistics
from collections import defaultdict
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "runtime.log"
LINE_RE = re.compile(
    r"""
    ^
    \[[^\]]+\]\s+
    (?P<req>[a-zA-Z0-9\-]+)\s+
    (?P<job>[a-zA-Z0-9_<>-]+)\s+
    (?P<time>[0-9]+(?:\.[0-9]+)?)ms
    """,
    re.VERBOSE,
)


def parse_timings() -> dict[str, list[float]]:
    timings: dict[str, list[float]] = defaultdict(list)
    if not LOG_PATH.exists():
        return timings
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        match = LINE_RE.match(line.strip())
        if not match:
            continue
        job = match.group("job")
        elapsed = float(match.group("time"))
        timings[job].append(elapsed)
    return timings


def main() -> None:
    timings = parse_timings()
    if not timings:
        print("No timing records found in logs/runtime.log")
        return

    print("Stage".ljust(32), "samples".rjust(8), "median(ms)".rjust(14), "p95(ms)".rjust(12))
    print("-" * 70)
    for job in sorted(timings.keys()):
        samples = timings[job]
        median = statistics.median(samples)
        p95 = statistics.quantiles(samples, n=20)[18] if len(samples) >= 20 else max(samples)
        print(job.ljust(32), str(len(samples)).rjust(8), f"{median:.2f}".rjust(14), f"{p95:.2f}".rjust(12))


if __name__ == "__main__":
    main()
