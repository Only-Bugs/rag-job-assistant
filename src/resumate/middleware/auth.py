"""Auth middleware: JWT, password hashing, user store, get_current_user dependency.

This module contains the core auth infrastructure. Route handlers live in
``resumate.routes.auth``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, Request
from jose import JWTError, jwt

logger = logging.getLogger("resumate")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_AUTH_DIR = _PROJECT_ROOT / "data" / "auth"
_DATA_USERS_DIR = _PROJECT_ROOT / "data" / "users"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("AUTH_REDIRECT_URI", "http://localhost:8000/auth/callback")

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30

AUTH_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

_GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO = "https://www.googleapis.com/oauth2/v3/userinfo"


# ---------------------------------------------------------------------------
# JWT secret — persistent across restarts
# ---------------------------------------------------------------------------
def _get_jwt_secret() -> str:
    env_val = os.getenv("JWT_SECRET")
    if env_val:
        return env_val
    secret_path = _PROJECT_ROOT / "data" / ".jwt_secret"
    if secret_path.exists():
        return secret_path.read_text(encoding="utf-8").strip()
    secret = secrets.token_hex(32)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(secret, encoding="utf-8")
    logger.info("auth: generated persistent JWT secret -> %s", secret_path)
    return secret


JWT_SECRET = _get_jwt_secret()

if not AUTH_ENABLED:
    logger.info(
        "auth: GOOGLE_CLIENT_ID/SECRET not set -- running in dev mode (user=dev_user)"
    )


# ---------------------------------------------------------------------------
# Password helpers (PBKDF2-HMAC-SHA256, 600k iterations — OWASP 2023)
# ---------------------------------------------------------------------------
def _hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    if salt is None:
        salt = secrets.token_bytes(32)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    return dk.hex(), salt.hex()


def _verify_password(password: str, stored_hash: str, stored_salt: str) -> bool:
    salt = bytes.fromhex(stored_salt)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000)
    return secrets.compare_digest(dk.hex(), stored_hash)


# ---------------------------------------------------------------------------
# User store — JSON file at data/auth/users.json
# ---------------------------------------------------------------------------
def _user_store_path() -> Path:
    return _AUTH_DIR / "users.json"


def _load_user_store() -> dict:
    path = _user_store_path()
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_user_store(store: dict) -> None:
    _AUTH_DIR.mkdir(parents=True, exist_ok=True)
    path = _user_store_path()
    with path.open("w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------
def _create_session_token(
    user_id: str, email: str, name: str, picture: str = ""
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "email": email,
        "name": name,
        "picture": picture,
        "exp": expire,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_session_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def _set_session_cookie(
    response, user_id: str, email: str, name: str, picture: str = ""
):
    token = _create_session_token(user_id, email, name, picture)
    response.set_cookie(
        key="rja_session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=JWT_EXPIRE_DAYS * 86400,
    )


# ---------------------------------------------------------------------------
# Dependency — inject into every protected route
# ---------------------------------------------------------------------------
_DEV_USER = {"user_id": "dev_user", "email": "dev@local", "name": "Dev User", "picture": ""}


def get_current_user(request: Request) -> dict:
    """FastAPI dependency: returns ``{"user_id", "email", "name"}``.

    - Dev mode (no Google creds): always returns _DEV_USER.
    - Auth mode: reads ``rja_session`` cookie; 401 for API, redirect for browser.
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
        "email": payload.get("email", ""),
        "name": payload.get("name", ""),
        "picture": payload.get("picture", ""),
    }


def _unauthenticated(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    raise HTTPException(
        status_code=401,
        detail={"error": "unauthenticated", "login_url": "/login"},
    )


def check_session(request: Request) -> dict | None:
    """Non-throwing session check for page guards. Always checks the cookie."""
    token = request.cookies.get("rja_session")
    if not token:
        return None
    try:
        payload = _decode_session_token(token)
        return {
            "user_id": payload["sub"],
            "email": payload.get("email", ""),
            "name": payload.get("name", ""),
            "picture": payload.get("picture", ""),
        }
    except JWTError:
        return None
