"""Application history CRUD — save, list, and load generated outputs."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from resumate.config.settings import get_user_data_dir
from resumate.middleware.auth import get_current_user

logger = logging.getLogger("resumate")
router = APIRouter(tags=["applications"])


class ApplicationSaveRequest(BaseModel):
    jd_text: str
    jd_preview: str | None = None
    content: dict[str, str]  # {skills, cover, emails, ats}


def _apps_dir(user_id: str) -> Path:
    d = get_user_data_dir(user_id) / "applications"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── POST /api/applications — save a generation ──────────────────────

@router.post("/api/applications")
async def save_application(request: Request, body: ApplicationSaveRequest):
    user = get_current_user(request)
    app_id = str(int(time.time() * 1000))
    app_data = {
        "id": app_id,
        "created_at": time.time(),
        "jd_text": body.jd_text,
        "jd_preview": (body.jd_preview or body.jd_text[:120]).strip(),
        "content": body.content,
        "tasks_completed": [k for k, v in body.content.items() if v],
    }

    path = _apps_dir(user["user_id"]) / f"{app_id}.json"
    path.write_text(json.dumps(app_data, ensure_ascii=False, indent=2))
    logger.info("application saved: %s for user %s", app_id, user["user_id"])
    return {"id": app_id, "status": "saved"}


# ── GET /api/applications — list saved applications ─────────────────

@router.get("/api/applications")
async def list_applications(request: Request):
    user = get_current_user(request)
    apps_dir = _apps_dir(user["user_id"])

    apps = []
    for f in sorted(apps_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            apps.append({
                "id": data["id"],
                "created_at": data.get("created_at", 0),
                "jd_preview": data.get("jd_preview", ""),
                "tasks_completed": data.get("tasks_completed", []),
            })
        except (json.JSONDecodeError, KeyError):
            continue

    return {"applications": apps[:50]}


# ── GET /api/applications/{app_id} — load a specific application ────

@router.get("/api/applications/{app_id}")
async def get_application(request: Request, app_id: str):
    user = get_current_user(request)
    path = _apps_dir(user["user_id"]) / f"{app_id}.json"

    if not path.exists():
        raise HTTPException(404, "Application not found")

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, KeyError) as exc:
        raise HTTPException(500, "Corrupt application data") from exc

    return data


# ── DELETE /api/applications/{app_id} — delete an application ───────

@router.delete("/api/applications/{app_id}")
async def delete_application(request: Request, app_id: str):
    user = get_current_user(request)
    path = _apps_dir(user["user_id"]) / f"{app_id}.json"

    if not path.exists():
        raise HTTPException(404, "Application not found")

    path.unlink()
    logger.info("application deleted: %s for user %s", app_id, user["user_id"])
    return {"status": "deleted"}
