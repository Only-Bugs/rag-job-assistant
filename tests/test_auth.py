"""Tests for /auth/* endpoints."""

from __future__ import annotations

import json
from unittest.mock import patch


def test_auth_me_dev_mode(client):
    """In dev mode, /auth/me should return the dev_user."""
    resp = client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == "dev_user"
    assert data["email"] == "dev@local"


def test_auth_login_dev_mode(client):
    """In dev mode, /auth/login should redirect to / (no Google)."""
    resp = client.get("/auth/login", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/"


def test_auth_logout(client):
    """Logout should redirect and clear the session cookie."""
    resp = client.get("/auth/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


def test_auth_config(client):
    """Config endpoint should report available providers."""
    resp = client.get("/auth/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] is True
    assert "google" in data


def test_register_and_signin(client, tmp_data_dir):
    """Full registration + signin round-trip."""
    store_path = tmp_data_dir / "auth_users.json"
    with patch("resumate.middleware.auth._user_store_path", return_value=store_path), \
         patch("resumate.middleware.auth._AUTH_DIR", tmp_data_dir), \
         patch("resumate.middleware.auth.AUTH_ENABLED", True):
        # Register
        resp = client.post("/auth/register", json={
            "email": "test@example.com",
            "password": "SecurePass123!",
            "name": "Test User",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["user_id"].startswith("em_")

        # Duplicate registration should fail
        resp = client.post("/auth/register", json={
            "email": "test@example.com",
            "password": "AnotherPass1!",
            "name": "Dupe User",
        })
        assert resp.status_code == 409

        # Sign in with correct password
        resp = client.post("/auth/signin", json={
            "email": "test@example.com",
            "password": "SecurePass123!",
        })
        assert resp.status_code == 200

        # Sign in with wrong password
        resp = client.post("/auth/signin", json={
            "email": "test@example.com",
            "password": "WrongPassword",
        })
        assert resp.status_code == 401


def test_register_validation(client, tmp_data_dir):
    """Registration should validate inputs."""
    store_path = tmp_data_dir / "auth_users.json"
    with patch("resumate.middleware.auth._user_store_path", return_value=store_path), \
         patch("resumate.middleware.auth._AUTH_DIR", tmp_data_dir):
        # Short password
        resp = client.post("/auth/register", json={
            "email": "a@b.com", "password": "short", "name": "X",
        })
        assert resp.status_code == 400

        # Invalid email
        resp = client.post("/auth/register", json={
            "email": "notanemail", "password": "LongEnough1!", "name": "X",
        })
        assert resp.status_code == 400

        # Empty name
        resp = client.post("/auth/register", json={
            "email": "a@b.com", "password": "LongEnough1!", "name": "",
        })
        assert resp.status_code == 400
