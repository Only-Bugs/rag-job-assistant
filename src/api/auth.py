"""Google OAuth 2.0 + JWT session auth for RJA.

When GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set the module operates in
*dev mode*: every request is treated as `dev_user` with no redirect.  This lets
the app run fully offline/local without any Google credentials configured.

Flow (when credentials ARE set):
  GET /auth/login      → redirect to Google consent screen
  GET /auth/callback   → exchange code, write HTTP-only JWT cookie, redirect /
  GET /auth/logout     → clear cookie, redirect /auth/login
  GET /auth/me         → return current user info (JSON)

All protected routes call ``Depends(get_current_user)`` which:
  - Returns dev_user dict when AUTH_ENABLED=False
  - Reads + verifies the JWT cookie when AUTH_ENABLED=True
  - Raises 401 (JSON) for API requests, redirect for browser requests
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from jose import JWTError, jwt

logger = logging.getLogger("api")
router = APIRouter(prefix="/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Config — read from environment, never hardcoded
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI         = os.getenv("AUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")

# JWT_SECRET must be stable across restarts in production (set it in .env).
# Falls back to a per-process random value — fine for local dev, sessions
# won't survive a server restart.
JWT_SECRET    = os.getenv("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30

AUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

_GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO  = "https://www.googleapis.com/oauth2/v3/userinfo"

if not AUTH_ENABLED:
    logger.info(
        "auth: GOOGLE_CLIENT_ID/SECRET not set — running in dev mode (user=dev_user)"
    )


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------
def _create_session_token(user_id: str, email: str, name: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {
        "sub":   user_id,
        "email": email,
        "name":  name,
        "exp":   expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_session_token(token: str) -> dict:
    """Decode and verify a session JWT.  Raises JWTError on failure."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ---------------------------------------------------------------------------
# Dependency — inject into every protected route
# ---------------------------------------------------------------------------
_DEV_USER = {"user_id": "dev_user", "email": "dev@local", "name": "Dev User"}


def get_current_user(request: Request) -> dict:
    """FastAPI dependency that returns ``{"user_id", "email", "name"}``.

    - Dev mode (no Google creds): always returns _DEV_USER.
    - Auth mode: reads ``rja_session`` cookie; returns 401 JSON for API
      requests, redirects to /auth/login for browser requests.
    """
    if not AUTH_ENABLED:
        return _DEV_USER

    token = request.cookies.get("rja_session")
    if not token:
        return _unauthenticated(request)

    try:
        payload = _decode_session_token(token)
    except JWTError:
        return _unauthenticated(request)

    return {
        "user_id": payload["sub"],
        "email":   payload.get("email", ""),
        "name":    payload.get("name", ""),
    }


def _unauthenticated(request: Request):
    """Return 401 JSON for API clients, redirect for browsers."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        # Browser — send to login
        from fastapi.responses import RedirectResponse as RR
        raise HTTPException(status_code=307, headers={"Location": "/auth/login"})
    raise HTTPException(
        status_code=401,
        detail={"error": "unauthenticated", "login_url": "/auth/login"},
    )


# ---------------------------------------------------------------------------
# OAuth routes
# ---------------------------------------------------------------------------
@router.get("/login")
async def login(request: Request):
    """Redirect to Google OAuth consent screen."""
    if not AUTH_ENABLED:
        return RedirectResponse("/")

    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state

    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile",
        "state":         state,
        "access_type":   "offline",
        "prompt":        "select_account",
    }
    return RedirectResponse(f"{_GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def callback(code: str, state: str, request: Request):
    """Exchange Google auth code for tokens, create session cookie."""
    # State check (CSRF protection)
    expected_state = request.session.pop("oauth_state", None)
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    # Exchange code for access token
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code":          code,
                "client_id":     GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri":  REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
        )

    if token_resp.status_code != 200:
        logger.error("auth: token exchange failed — %s", token_resp.text)
        raise HTTPException(status_code=502, detail="Google token exchange failed")

    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token in Google response")

    # Fetch user profile via userinfo endpoint
    async with httpx.AsyncClient(timeout=10.0) as client:
        info_resp = await client.get(
            _GOOGLE_USERINFO,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if info_resp.status_code != 200:
        logger.error("auth: userinfo fetch failed — %s", info_resp.text)
        raise HTTPException(status_code=502, detail="Google userinfo fetch failed")

    user_info = info_resp.json()
    user_id = user_info.get("sub")
    email   = user_info.get("email", "")
    name    = user_info.get("name", email)

    if not user_id:
        raise HTTPException(status_code=502, detail="Google did not return a user sub")

    logger.info("auth: login OK  user_id=%s  email=%s", user_id, email)

    session_token = _create_session_token(user_id, email, name)
    response = RedirectResponse("/", status_code=302)
    response.set_cookie(
        key="rja_session",
        value=session_token,
        httponly=True,
        samesite="lax",
        max_age=JWT_EXPIRE_DAYS * 86400,
    )
    return response


@router.get("/logout")
async def logout():
    """Clear session cookie and redirect to login."""
    response = RedirectResponse("/auth/login", status_code=302)
    response.delete_cookie("rja_session")
    return response


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    """Return current user info as JSON."""
    return user
