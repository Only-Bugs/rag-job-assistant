"""Google Drive upload route: POST /api/drive/upload + GET /api/drive/status."""

from __future__ import annotations

import base64
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from resumate.middleware.auth import get_current_user
from resumate.routes.auth import get_valid_google_token, load_google_tokens

logger = logging.getLogger("resumate")
router = APIRouter(prefix="/api/drive", tags=["drive"])

_DRIVE_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"


class DriveUploadBody(BaseModel):
    filename: str
    content_base64: str
    mime_type: str  # e.g. "application/pdf" or "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get("/status")
async def drive_status(user: dict = Depends(get_current_user)):
    """Check if the user has Google tokens stored (Drive available)."""
    tokens = load_google_tokens(user["user_id"])
    connected = bool(tokens and tokens.get("access_token"))
    return {"connected": connected}


@router.post("/upload")
async def drive_upload(payload: DriveUploadBody, user: dict = Depends(get_current_user)):
    """Upload a file to the user's Google Drive."""
    user_id = user["user_id"]

    access_token = await get_valid_google_token(user_id)
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail="Google Drive not connected. Please re-login with Google to grant permissions.",
        )

    try:
        file_bytes = base64.b64decode(payload.content_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 content")

    # Build multipart body per Drive API v3 spec
    import json
    metadata = json.dumps({"name": payload.filename}).encode("utf-8")

    boundary = "resumate_drive_boundary"
    body = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode("utf-8")
    body += metadata
    body += (
        f"\r\n--{boundary}\r\n"
        f"Content-Type: {payload.mime_type}\r\n\r\n"
    ).encode("utf-8")
    body += file_bytes
    body += f"\r\n--{boundary}--".encode("utf-8")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _DRIVE_UPLOAD_URL,
            content=body,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": f"multipart/related; boundary={boundary}",
            },
        )

    if resp.status_code == 200:
        file_id = resp.json().get("id", "")
        logger.info("drive: uploaded file=%s id=%s user_id=%s", payload.filename, file_id, user_id)
        return {"status": "uploaded", "file_id": file_id, "filename": payload.filename}

    logger.error("drive: upload failed status=%s body=%s", resp.status_code, resp.text)
    raise HTTPException(
        status_code=502,
        detail=f"Drive API error ({resp.status_code}): {resp.json().get('error', {}).get('message', resp.text)}",
    )
