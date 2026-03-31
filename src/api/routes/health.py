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
    """Return API liveness status and Ollama reachability."""
    ollama_reachable = await _check_ollama()
    return {
        "status": "ok" if ollama_reachable else "degraded",
        "model": MODEL_NAME,
        "ollama_reachable": ollama_reachable,
    }


async def _check_ollama() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(OLLAMA_HOST.rstrip("/"))
        return response.status_code < 500
    except Exception:
        return False
