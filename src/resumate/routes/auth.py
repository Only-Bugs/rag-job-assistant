"""Auth route handlers: /auth/* endpoints.

Core auth infrastructure (JWT, password hashing, user store) lives in
``resumate.middleware.auth``.
"""

from __future__ import annotations

import io
import json
import logging
import secrets
import shutil
import uuid
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from resumate.middleware.auth import (
    AUTH_ENABLED,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    REDIRECT_URI,
    _AUTH_DIR,
    _DATA_USERS_DIR,
    _GOOGLE_AUTH_URL,
    _GOOGLE_TOKEN_URL,
    _GOOGLE_USERINFO,
    _hash_password,
    _load_user_store,
    _save_user_store,
    _set_session_cookie,
    _verify_password,
    get_current_user,
)

logger = logging.getLogger("resumate")
router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class RegisterBody(BaseModel):
    email: str
    password: str
    name: str


class SigninBody(BaseModel):
    email: str
    password: str


# ---------------------------------------------------------------------------
# Auth config (public -- tells the frontend which providers are available)
# ---------------------------------------------------------------------------
@router.get("/config")
async def auth_config():
    return {"google": AUTH_ENABLED, "email": True}


# ---------------------------------------------------------------------------
# Email/password -- register
# ---------------------------------------------------------------------------
@router.post("/register")
async def register(body: RegisterBody):
    email = body.email.strip().lower()
    name = body.name.strip()

    if not email or "@" not in email:
        raise HTTPException(400, detail="Please enter a valid email address.")
    if len(body.password) < 8:
        raise HTTPException(400, detail="Password must be at least 8 characters.")
    if not name:
        raise HTTPException(400, detail="Please enter your name.")

    store = _load_user_store()
    if email in store:
        raise HTTPException(409, detail="An account with this email already exists.")

    user_id = f"em_{uuid.uuid4().hex[:16]}"
    pw_hash, salt = _hash_password(body.password)

    store[email] = {
        "user_id": user_id,
        "name": name,
        "password_hash": pw_hash,
        "salt": salt,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_user_store(store)

    logger.info("auth: registered user_id=%s email=%s", user_id, email)

    response = JSONResponse({"status": "ok", "user_id": user_id})
    _set_session_cookie(response, user_id, email, name)
    return response


# ---------------------------------------------------------------------------
# Email/password -- sign in
# ---------------------------------------------------------------------------
@router.post("/signin")
async def signin(body: SigninBody):
    email = body.email.strip().lower()

    store = _load_user_store()
    user = store.get(email)
    if not user:
        raise HTTPException(401, detail="Invalid email or password.")

    if not _verify_password(body.password, user["password_hash"], user["salt"]):
        raise HTTPException(401, detail="Invalid email or password.")

    user_id = user["user_id"]
    name = user["name"]
    logger.info("auth: signin OK user_id=%s email=%s", user_id, email)

    response = JSONResponse({"status": "ok", "user_id": user_id})
    _set_session_cookie(response, user_id, email, name)
    return response


# ---------------------------------------------------------------------------
# Google OAuth routes
# ---------------------------------------------------------------------------
@router.get("/login")
async def login(request: Request):
    if not AUTH_ENABLED:
        return RedirectResponse("/")

    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/drive.file",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return RedirectResponse(f"{_GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def callback(code: str, state: str, request: Request):
    expected_state = request.session.pop("oauth_state", None)
    if not expected_state or state != expected_state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )

    if token_resp.status_code != 200:
        logger.error("auth: token exchange failed -- %s", token_resp.text)
        raise HTTPException(status_code=502, detail="Google token exchange failed")

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="No access_token in Google response")

    async with httpx.AsyncClient(timeout=10.0) as client:
        info_resp = await client.get(
            _GOOGLE_USERINFO,
            headers={"Authorization": f"Bearer {access_token}"},
        )

    if info_resp.status_code != 200:
        logger.error("auth: userinfo fetch failed -- %s", info_resp.text)
        raise HTTPException(status_code=502, detail="Google userinfo fetch failed")

    user_info = info_resp.json()
    user_id = user_info.get("sub")
    email = user_info.get("email", "")
    name = user_info.get("name", email)
    picture = user_info.get("picture", "")

    if not user_id:
        raise HTTPException(status_code=502, detail="Google did not return a user sub")

    # Store Google tokens for Gmail/Drive API access
    _store_google_tokens(user_id, access_token, refresh_token)

    logger.info("auth: login OK user_id=%s email=%s", user_id, email)

    response = RedirectResponse("/", status_code=302)
    _set_session_cookie(response, user_id, email, name, picture)
    return response


# ---------------------------------------------------------------------------
# Google token storage helpers
# ---------------------------------------------------------------------------
def _google_tokens_path(user_id: str):
    """Return the path to a user's Google tokens file."""
    return _DATA_USERS_DIR / user_id / "google_tokens.json"


def _store_google_tokens(
    user_id: str, access_token: str, refresh_token: str | None
) -> None:
    """Persist Google OAuth tokens for a user."""
    path = _google_tokens_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Preserve existing refresh_token if a new one wasn't issued
    existing = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    tokens = {
        "access_token": access_token,
        "refresh_token": refresh_token or existing.get("refresh_token"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
    logger.info("auth: stored google tokens for user_id=%s", user_id)


def load_google_tokens(user_id: str) -> dict | None:
    """Load stored Google tokens for a user. Returns None if not found."""
    path = _google_tokens_path(user_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


async def get_valid_google_token(user_id: str) -> str | None:
    """Return a valid Google access token, refreshing if needed.

    Returns None if no tokens are stored or refresh fails.
    """
    tokens = load_google_tokens(user_id)
    if not tokens or not tokens.get("access_token"):
        return None

    # Try the stored access token first (quick validation via userinfo)
    async with httpx.AsyncClient(timeout=10.0) as client:
        check = await client.get(
            _GOOGLE_USERINFO,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )

    if check.status_code == 200:
        return tokens["access_token"]

    # Token expired — try refreshing
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return None

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            _GOOGLE_TOKEN_URL,
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )

    if resp.status_code != 200:
        logger.warning("auth: token refresh failed for user_id=%s -- %s", user_id, resp.text)
        return None

    new_access = resp.json().get("access_token")
    if new_access:
        _store_google_tokens(user_id, new_access, refresh_token)
        return new_access

    return None


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("rja_session")
    return response


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user


# ---------------------------------------------------------------------------
# Account management
# ---------------------------------------------------------------------------
@router.delete("/account")
async def delete_account(user: dict = Depends(get_current_user)):
    """Delete the current user's account and all associated data."""
    user_id = user["user_id"]
    email = user.get("email", "")

    store = _load_user_store()
    store = {k: v for k, v in store.items() if v.get("user_id") != user_id}
    _save_user_store(store)

    user_dir = _DATA_USERS_DIR / user_id
    if user_dir.exists():
        shutil.rmtree(user_dir)
        logger.info("auth: deleted user data dir %s", user_dir)

    logger.info("auth: deleted account user_id=%s email=%s", user_id, email)

    response = JSONResponse({"status": "deleted"})
    response.delete_cookie("rja_session")
    return response


@router.get("/export-data")
async def export_data(user: dict = Depends(get_current_user)):
    """Download a ZIP of the current user's data directory."""
    user_id = user["user_id"]
    user_dir = _DATA_USERS_DIR / user_id

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if user_dir.exists():
            for f in user_dir.rglob("*"):
                if f.is_file():
                    arcname = f.relative_to(user_dir)
                    zf.write(f, arcname)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="resumate_data_{user_id}.zip"'},
    )
