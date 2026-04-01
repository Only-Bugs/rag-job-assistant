"""GET /profile and POST /profile — profile CRUD endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.auth import get_current_user
from rag.profile.service import load_profile, save_profile
from rag.config.settings import get_user_data_dir

logger = logging.getLogger("api")
router = APIRouter()


class ProfileBody(BaseModel):
    model_config = {"extra": "allow"}  # accept any field the client sends


@router.get("/profile")
async def get_profile(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return the active profile as JSON. Returns empty dict if not yet created."""
    try:
        return load_profile(get_user_data_dir(user["user_id"]))
    except Exception as exc:
        logger.warning("get_profile: could not load — %s", exc)
        return {}


@router.post("/profile")
async def post_profile(
    body: ProfileBody,
    user: dict = Depends(get_current_user),
) -> dict[str, str]:
    """Persist the full profile object."""
    save_profile(body.model_dump(), get_user_data_dir(user["user_id"]))
    return {"status": "saved"}
