"""Parse logs/performance.json and report TTFT / total latency per task."""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[1] / "logs" / "performance.json"


def load_records() -> list[dict]:
    if not LOG_PATH.exists():
        return []
    records: list[dict] = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _median(vals: list[float]) -> str:
    return f"{statistics.median(vals):.1f}" if vals else "N/A"


def _p95(vals: list[float]) -> str:
    if not vals:
        return "N/A"
    if len(vals) >= 20:
        return f"{statistics.quantiles(vals, n=20)[18]:.1f}"
    return f"{max(vals):.1f}"


def main() -> None:
    records = load_records()
    if not records:
        print(f"No records found in {LOG_PATH}")
        return

    ttft_by_task: dict[str, list[float]] = defaultdict(list)
    total_by_task: dict[str, list[float]] = defaultdict(list)
    errors_by_task: dict[str, int] = defaultdict(int)

    for rec in records:
        task = rec.get("task_name", "unknown")
        status = rec.get("status", "ok")
        total_ms = rec.get("total_ms")
        ttft_ms = rec.get("ttft_ms")

        if status != "ok":
            errors_by_task[task] += 1
        if total_ms is not None:
            total_by_task[task].append(float(total_ms) / 1000)
        if ttft_ms is not None:
            ttft_by_task[task].append(float(ttft_ms) / 1000)

    tasks = sorted(set(list(ttft_by_task) + list(total_by_task)))
    total_errors = sum(errors_by_task.values())

    print(f"\nPerformance report  —  {len(records)} records  |  {LOG_PATH}\n")
    col = [18, 7, 15, 12, 16, 13, 7]
    hdr = (
        f"{'Task':<{col[0]}} {'n':>{col[1]}} {'TTFT med(s)':>{col[2]}}"
        f" {'TTFT p95(s)':>{col[3]}} {'Total med(s)':>{col[4]}}"
        f" {'Total p95(s)':>{col[5]}} {'Errors':>{col[6]}}"
    )
    print(hdr)
    print("-" * len(hdr))

    for task in tasks:
        ttfts = ttft_by_task[task]
        totals = total_by_task[task]
        n = len(totals)
        errs = errors_by_task[task]
        print(
            f"{task:<{col[0]}} {n:>{col[1]}} {_median(ttfts):>{col[2]}}"
            f" {_p95(ttfts):>{col[3]}} {_median(totals):>{col[4]}}"
            f" {_p95(totals):>{col[5]}} {errs:>{col[6]}}"
        )

    print(f"\nTotals: {len(records)} data points, {total_errors} errors\n")


if __name__ == "__main__":
    main()
