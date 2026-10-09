"""GET /profile and POST /profile -- profile CRUD endpoints."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from resumate.middleware.auth import get_current_user
from resumate.services.profile import load_profile, save_profile
from resumate.services.ingestion import index_profile_docs
from resumate.config.settings import get_user_data_dir

logger = logging.getLogger("resumate")
router = APIRouter()


class ProfileBody(BaseModel):
    model_config = {"extra": "allow"}


@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return the active profile as JSON."""
    try:
        return load_profile(get_user_data_dir(user["user_id"]))
    except Exception as exc:
        logger.warning("get_profile: could not load -- %s", exc)
        return {}


@router.post("/profile")
async def post_profile(
    body: ProfileBody,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Persist the full profile object."""
    save_profile(body.model_dump(), get_user_data_dir(user["user_id"]))
    return {"status": "saved"}


@router.post("/profile/reindex")
async def reindex_profile(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Force re-ingest of the user's profile_docs directory."""
    user_dir = get_user_data_dir(user["user_id"])
    profile_doc_dir = user_dir / "profile_docs"
    if not profile_doc_dir.exists():
        raise HTTPException(status_code=404, detail="profile_docs directory missing")
    files = sorted(p.name for p in profile_doc_dir.iterdir() if p.is_file())

    t0 = time.monotonic()
    try:
        chunks = index_profile_docs(user_dir, force=True)
    except Exception as exc:
        logger.exception("reindex failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"reindex failed: {exc}")
    duration_ms = int((time.monotonic() - t0) * 1000)

    logger.info("profile reindex: %d chunks in %dms (%d files)", chunks, duration_ms, len(files))
    return {
        "status": "ok",
        "duration_ms": duration_ms,
        "chunks": chunks,
        "files": files,
    }
