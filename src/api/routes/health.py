"""GET /health — liveness and dependency check."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter

from rag.config.settings import MODEL_NAME, OLLAMA_HOST

logger = logging.getLogger("api")
router = APIRouter()


@router.get("/health")
async def health() -> dict:
    """Return API liveness status, Ollama reachability, and compute mode."""
    ollama_reachable = await _check_ollama()
    compute = await _check_compute_mode() if ollama_reachable else "unknown"
    if compute == "cpu":
        logger.warning(
            "Model is running on CPU — Metal GPU offload failed or not available. "
            "Expect 10-100x slower inference. Restart Ollama with more free RAM to recover."
        )
    model_ready = compute in ("metal", "cpu")
    return {
        "status": "ok" if ollama_reachable else "degraded",
        "model": MODEL_NAME,
        "ollama_reachable": ollama_reachable,
        "compute": compute,
        "model_ready": model_ready,
    }


async def _check_ollama() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(OLLAMA_HOST.rstrip("/"))
        return response.status_code < 500
    except Exception:
        return False


async def _check_compute_mode() -> str:
    """Query Ollama /api/ps to detect whether the model is running on Metal or CPU.

    Returns "metal", "cpu", "not_loaded", or "unknown".
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_HOST.rstrip('/')}/api/ps")
        if resp.status_code != 200:
            return "unknown"
        data = resp.json()
        models = data.get("models") or []
        for entry in models:
            if MODEL_NAME in entry.get("name", ""):
                details = entry.get("details") or {}
                # size_vram > 0 means layers are offloaded to GPU
                size_vram = entry.get("size_vram", 0)
                if size_vram and int(size_vram) > 0:
                    return "metal"
                return "cpu"
        return "not_loaded"
    except Exception:
        return "unknown"
