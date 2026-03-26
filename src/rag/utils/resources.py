"""
Heuristics for clamping LLM parallel worker count when using Ollama.

Ollama keeps model weights resident once loaded; concurrent chat requests share
those weights. Extra concurrency mainly adds per-request KV cache (order ~100MB
for a small model), not a full extra model copy — so RAM-based guards should
not assume multi-gigabytes per worker.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger("rag")

# Per concurrent request beyond shared weights (KV cache, activations), in GiB.
_KV_CACHE_COST_GIB = float(os.getenv("RAG_LLM_KV_CACHE_GIB_PER_WORKER", "0.15"))
# Leave headroom for OS, Streamlit, Chroma, etc.
_MIN_FREE_HEADROOM_GIB = float(os.getenv("RAG_LLM_MIN_FREE_HEADROOM_GIB", "0.5"))
_MAX_CAP = 8


def _nvidia_free_gib() -> Optional[float]:
    try:
        import subprocess

        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode != 0 or not out.stdout.strip():
            return None
        lines = [ln.strip() for ln in out.stdout.strip().splitlines() if ln.strip()]
        values = [float(ln) / 1024.0 for ln in lines]
        return min(values) if values else None
    except (FileNotFoundError, OSError, ValueError):
        return None


def effective_parallel_workers(configured: int) -> int:
    """
    Return a worker count in [1, configured].

    Prefer ``LLM_PARALLEL_WORKERS_OVERRIDE`` (see ``.env.example``), then
    ``RAG_LLM_PARALLEL_WORKERS`` for backward compatibility.

    Otherwise estimate affordability from free RAM (and, if available, free GPU
    memory) using a small per-worker cost suitable for Ollama, not full model size.
    """
    desired = max(1, min(int(configured), _MAX_CAP))

    for env_name in ("LLM_PARALLEL_WORKERS_OVERRIDE", "RAG_LLM_PARALLEL_WORKERS"):
        forced = os.getenv(env_name)
        if forced is None or str(forced).strip() == "":
            continue
        try:
            n = max(1, min(int(str(forced).strip()), _MAX_CAP))
        except ValueError:
            logger.warning("Ignoring invalid %s=%r; using Ollama-aware heuristics", env_name, forced)
            break
        logger.info(
            "[resources] Worker count from %s=%s (configured=%s)",
            env_name,
            n,
            configured,
        )
        return n

    try:
        import psutil

        avail_gib = psutil.virtual_memory().available / (1024**3)
    except Exception:
        avail_gib = None

    affordable_ram: Optional[int] = None
    if avail_gib is not None:
        affordable_ram = int((avail_gib - _MIN_FREE_HEADROOM_GIB) / _KV_CACHE_COST_GIB)

    free_gpu_gib = _nvidia_free_gib()
    affordable_gpu: Optional[int] = None
    if free_gpu_gib is not None:
        affordable_gpu = int((free_gpu_gib - _MIN_FREE_HEADROOM_GIB) / _KV_CACHE_COST_GIB)

    cap_candidates = [desired]
    if affordable_ram is not None:
        cap_candidates.append(max(1, affordable_ram))
    if affordable_gpu is not None:
        cap_candidates.append(max(1, affordable_gpu))

    effective = max(1, min(cap_candidates))
    if effective < desired:
        logger.warning(
            "[resources] Workers reduced %s -> %s (KV-cache heuristic; "
            "set LLM_PARALLEL_WORKERS_OVERRIDE to force)",
            desired,
            effective,
        )
    else:
        ram_part = f"{avail_gib:.2f}GiB" if avail_gib is not None else "n/a"
        logger.info(
            "[resources] RAM available: %s | affordable_ram: %s | affordable_gpu: %s | effective: %s (desired=%s)",
            ram_part,
            affordable_ram,
            affordable_gpu,
            effective,
            desired,
        )
    return effective


__all__ = ["effective_parallel_workers"]
