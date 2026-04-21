"""GET /profile and POST /profile -- profile CRUD endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from resumate.middleware.auth import get_current_user
from resumate.services.profile import load_profile, save_profile
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
