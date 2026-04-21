"""Tests for GET/POST /profile endpoints."""

from __future__ import annotations


def test_get_profile_fresh(client):
    """A fresh data dir should return the default profile (or empty dict)."""
    resp = client.get("/profile")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_save_and_load_profile(client):
    """POST then GET should round-trip the profile data."""
    payload = {"name": "Test User", "title": "Engineer", "skills": ["Python", "Rust"]}
    resp = client.post("/profile", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"

    resp = client.get("/profile")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test User"
    assert data["skills"] == ["Python", "Rust"]


def test_profile_extra_fields(client):
    """ProfileBody allows extra fields — they should be persisted."""
    payload = {"name": "X", "custom_field": "hello"}
    client.post("/profile", json=payload)
    data = client.get("/profile").json()
    assert data["custom_field"] == "hello"
