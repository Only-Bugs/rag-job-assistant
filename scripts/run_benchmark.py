"""Automated warm benchmark runner for the RJA generation pipeline.

Usage:
    python scripts/run_benchmark.py           # 3 warm runs
    python scripts/run_benchmark.py --runs 5  # 5 warm runs

The script:
  1. Verifies Ollama is running and the configured model is present.
  2. Sends a warm-up prompt so the model is resident in VRAM before timing starts.
  3. Runs generate_application_package() N times using the cached JD (data/job_rag/jd.txt).
  4. Prints output from benchmark_runtime.py and analyze_performance.py.
  5. Prints a summary with generation_sequential median/p95 and 90s target verdict.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from time import perf_counter
from typing import Optional

# ---------------------------------------------------------------------------
# Path bootstrap — must happen before any rag.* / ui.* imports
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# ---------------------------------------------------------------------------
# Project config — resolved after sys.path is set
# ---------------------------------------------------------------------------
from rag.config.settings import MODEL_NAME, OLLAMA_HOST, RAG_DIR  # noqa: E402

JD_PATH = RAG_DIR / "jd.txt"
RUNTIME_LOG = ROOT / "logs" / "runtime.log"
SCRIPTS_DIR = Path(__file__).resolve().parent

TARGET_MS = 90_000  # 90-second pipeline target

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
_W = 72


def _sep(char: str = "─") -> None:
    print(char * _W)


def _header(text: str, char: str = "═") -> None:
    _sep(char)
    print(text)
    _sep(char)


# ---------------------------------------------------------------------------
# Ollama helpers (stdlib only — no requests dependency)
# ---------------------------------------------------------------------------
def _ollama_get(path: str, timeout: int = 10) -> dict:
    url = f"{OLLAMA_HOST.rstrip('/')}{path}"
    with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout) as r:
        return json.loads(r.read())


def _ollama_post(path: str, payload: dict, timeout: int = 300) -> dict:
    url = f"{OLLAMA_HOST.rstrip('/')}{path}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------------------
# Step 1 — Verify Ollama is running and the model is present
# ---------------------------------------------------------------------------
def check_ollama(model_name: str) -> None:
    print(f"[check]  Connecting to Ollama at {OLLAMA_HOST} ...")
    try:
        data = _ollama_get("/api/tags")
    except urllib.error.URLError as exc:
        print(f"\n  ERROR: Cannot reach Ollama at {OLLAMA_HOST}")
        print(f"  Detail: {exc}")
        print(f"\n  Fix: OLLAMA_KEEP_ALIVE=24h ollama serve")
        sys.exit(1)

    models = [m.get("name", "") for m in data.get("models", [])]
    base = model_name.split(":")[0]
    found = any(m == model_name or m.startswith(base + ":") for m in models)

    if not found:
        print(f"\n  ERROR: Model '{model_name}' not found in Ollama.")
        print(f"  Available models: {models or '(none loaded)'}")
        print(f"\n  Fix: ollama pull {model_name}")
        sys.exit(1)

    print(f"  OK — '{model_name}' is present.")


# ---------------------------------------------------------------------------
# Step 2 — Warm the model
# ---------------------------------------------------------------------------
def warm_model(model_name: str) -> None:
    print(f"[warm]   Sending warm-up prompt to load model into VRAM ...")
    t0 = perf_counter()
    try:
        _ollama_post(
            "/api/generate",
            {"model": model_name, "prompt": "respond with ok", "stream": False},
        )
    except Exception as exc:
        print(f"  WARNING: Warm-up prompt failed: {exc}")
        print(f"  Continuing — first benchmark run may be slower than subsequent ones.")
        return
    print(f"  OK — warm-up complete ({perf_counter() - t0:.1f}s).")


# ---------------------------------------------------------------------------
# Step 3 — Load the cached JD
# ---------------------------------------------------------------------------
def load_jd() -> str:
    if not JD_PATH.exists():
        print(f"\n  ERROR: No cached JD found at {JD_PATH}")
        print(f"  Fix: run the Streamlit UI once with a pasted JD, then re-run this script.")
        sys.exit(1)
    text = JD_PATH.read_text(encoding="utf-8").strip()
    if not text:
        print(f"\n  ERROR: {JD_PATH} is empty.")
        print(f"  Fix: paste a JD in the Streamlit UI to populate the cache.")
        sys.exit(1)
    return text


# ---------------------------------------------------------------------------
# Step 3 (cont.) — Run the pipeline once
# ---------------------------------------------------------------------------
def _run_once(jd_text: str) -> tuple[bool, float, Optional[str]]:
    """Returns (success, elapsed_seconds, error_string|None)."""
    # Deferred import so the module is only loaded once (Python caches it) and
    # any Streamlit/logboard import side-effects happen after sys.path is ready.
    from rag.generation.generator import generate_application_package

    t0 = perf_counter()
    try:
        # generate_application_package is a generator; consume it fully.
        for _ in generate_application_package(jd_text, save_to_disk=False, progress=None):
            pass
        return True, perf_counter() - t0, None
    except Exception as exc:
        return False, perf_counter() - t0, str(exc)


def run_all(n: int, jd_text: str) -> tuple[list[float], list[str]]:
    """Run the pipeline n times. Returns (wall_times_for_successes, error_messages)."""
    wall_times: list[float] = []
    errors: list[str] = []

    for i in range(1, n + 1):
        _sep()
        print(f"[run {i}/{n}]  Starting ...")
        ok, elapsed, err = _run_once(jd_text)
        if ok:
            wall_times.append(elapsed)
            print(f"[run {i}/{n}]  Done — {elapsed:.1f}s")
        else:
            errors.append(f"Run {i}: {err}")
            print(f"[run {i}/{n}]  FAILED after {elapsed:.1f}s  —  {err}")

    return wall_times, errors


# ---------------------------------------------------------------------------
# Step 4 — Call the analysis scripts and capture their output
# ---------------------------------------------------------------------------
def _run_script(path: Path) -> str:
    result = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
    )
    out = result.stdout
    if result.stderr.strip():
        out += "\n" + result.stderr
    return out


# ---------------------------------------------------------------------------
# Summary helpers — parse only new runtime.log entries from this run
# ---------------------------------------------------------------------------
_LINE_RE = re.compile(
    r"""
    ^
    \[[^\]]+\]\s+
    (?P<req>[a-zA-Z0-9\-]+)\s+
    (?P<job>[a-zA-Z0-9_<>:\-]+)\s+
    (?P<time>[0-9]+(?:\.[0-9]+)?)ms
    """,
    re.VERBOSE,
)


def _log_byte_offset(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _sequential_timings_since(path: Path, offset: int) -> list[float]:
    """Read only bytes appended since `offset` and return generation_sequential timings."""
    if not path.exists():
        return []
    with path.open("rb") as fh:
        fh.seek(offset)
        new = fh.read().decode("utf-8", errors="replace")
    timings: list[float] = []
    for line in new.splitlines():
        m = _LINE_RE.match(line.strip())
        if m and m.group("job") == "generation_sequential":
            timings.append(float(m.group("time")))
    return timings


# ---------------------------------------------------------------------------
# Step 5 — Summary
# ---------------------------------------------------------------------------
def print_summary(
    n_attempted: int,
    wall_times: list[float],
    errors: list[str],
    seq_ms: list[float],
) -> None:
    _header("BENCHMARK SUMMARY")

    n_ok = len(wall_times)
    print(f"  Runs completed : {n_ok} / {n_attempted}")

    if wall_times:
        w_med = statistics.median(wall_times)
        w_max = max(wall_times)
        print(f"  Wall time      : median {w_med:.1f}s  /  max {w_max:.1f}s")

    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for e in errors:
            print(f"    • {e}")

    print()

    if seq_ms:
        med_ms = statistics.median(seq_ms)
        p95_ms = (
            statistics.quantiles(seq_ms, n=20)[18]
            if len(seq_ms) >= 20
            else max(seq_ms)
        )
        target_met = med_ms <= TARGET_MS
        verdict = "✓  TARGET MET" if target_met else "✗  TARGET NOT MET"

        print(f"  generation_sequential  ({len(seq_ms)} sample(s))")
        print(f"    median  :  {med_ms / 1000:.1f}s  ({med_ms:.0f}ms)")
        print(f"    p95     :  {p95_ms / 1000:.1f}s  ({p95_ms:.0f}ms)")
        print(f"    90s target — {verdict}  (target={TARGET_MS // 1000}s, median={med_ms / 1000:.1f}s)")
    else:
        print("  generation_sequential: no timings captured (check logs/runtime.log)")

    _sep("═")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Warm benchmark runner for the RJA generation pipeline."
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        metavar="N",
        help="Number of benchmark runs (default: 3)",
    )
    args = parser.parse_args()

    if args.runs < 1:
        print("ERROR: --runs must be >= 1")
        sys.exit(1)

    _header(f"RJA BENCHMARK RUNNER  —  {args.runs} run(s)  |  model: {MODEL_NAME}")

    # 1. Verify Ollama
    check_ollama(MODEL_NAME)

    # 2. Warm the model
    warm_model(MODEL_NAME)

    # 3. Load JD
    jd_text = load_jd()
    preview = jd_text[:80].replace("\n", " ")
    print(f'[jd]     {len(jd_text)} chars from {JD_PATH.name}  —  "{preview}..."')

    # Record log position so the summary only reflects this run's timings
    log_offset = _log_byte_offset(RUNTIME_LOG)

    # 4. Run the pipeline
    wall_times, errors = run_all(args.runs, jd_text)

    # 5. Extract generation_sequential timings from the new log entries
    seq_ms = _sequential_timings_since(RUNTIME_LOG, log_offset)

    # 6. Print analysis script output
    _sep()
    print("[benchmark_runtime.py]")
    _sep()
    print(_run_script(SCRIPTS_DIR / "benchmark_runtime.py"))

    _sep()
    print("[analyze_performance.py]")
    _sep()
    print(_run_script(SCRIPTS_DIR / "analyze_performance.py"))

    # 7. Summary
    print_summary(args.runs, wall_times, errors, seq_ms)


if __name__ == "__main__":
    main()
