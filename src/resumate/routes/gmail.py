"""Gmail send route: POST /api/gmail/send + GET /api/gmail/status."""

from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from resumate.middleware.auth import get_current_user
from resumate.routes.auth import get_valid_google_token, load_google_tokens

logger = logging.getLogger("resumate")
router = APIRouter(prefix="/api/gmail", tags=["gmail"])

_GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class SendEmailBody(BaseModel):
    to: str
    subject: str
    body: str


@router.get("/status")
async def gmail_status(user: dict = Depends(get_current_user)):
    """Check if the user has Google tokens stored (Gmail available)."""
    tokens = load_google_tokens(user["user_id"])
    connected = bool(tokens and tokens.get("access_token"))
    return {"connected": connected}


@router.post("/send")
async def gmail_send(payload: SendEmailBody, user: dict = Depends(get_current_user)):
    """Send an email via the user's Gmail account."""
    user_id = user["user_id"]

    access_token = await get_valid_google_token(user_id)
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail="Gmail not connected. Please re-login with Google to grant permissions.",
        )

    # Build MIME message
    msg = MIMEText(payload.body, "plain", "utf-8")
    msg["To"] = payload.to
    msg["Subject"] = payload.subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            _GMAIL_SEND_URL,
            json={"raw": raw},
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if resp.status_code == 200:
        msg_id = resp.json().get("id", "")
        logger.info("gmail: sent email to=%s msg_id=%s user_id=%s", payload.to, msg_id, user_id)
        return {"status": "sent", "message_id": msg_id}

    logger.error("gmail: send failed status=%s body=%s", resp.status_code, resp.text)
    raise HTTPException(
        status_code=502,
        detail=f"Gmail API error ({resp.status_code}): {resp.json().get('error', {}).get('message', resp.text)}",
    )
