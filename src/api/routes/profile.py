"""GET /profile and POST /profile — profile CRUD endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from rag.profile.service import load_profile, save_profile
from rag.config.settings import get_user_data_dir, DEV_USER_ID

logger = logging.getLogger("api")
router = APIRouter()

_USER_DATA_DIR = get_user_data_dir(DEV_USER_ID)


class ProfileBody(BaseModel):
    model_config = {"extra": "allow"}  # accept any field the client sends


@router.get("/profile")
async def get_profile() -> dict[str, Any]:
    """Return the active profile as JSON. Returns empty dict if not yet created."""
    try:
        return load_profile(_USER_DATA_DIR)
    except Exception as exc:
        logger.warning("get_profile: could not load — %s", exc)
        return {}


@router.post("/profile")
async def post_profile(body: ProfileBody) -> dict[str, str]:
    """Persist the full profile object."""
    save_profile(body.model_dump(), _USER_DATA_DIR)
    return {"status": "saved"}
