"""Tests for POST /upload, POST /ingest, GET /documents endpoints."""

from __future__ import annotations

from unittest.mock import patch


def test_upload_valid_txt(client):
    """Uploading a .txt file should succeed."""
    resp = client.post(
        "/upload",
        files={"file": ("resume.txt", b"My resume content", "text/plain")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "uploaded"
    assert data["filename"] == "resume.txt"


def test_upload_invalid_extension(client):
    """Uploading a disallowed extension should return 400."""
    resp = client.post(
        "/upload",
        files={"file": ("malware.exe", b"bad stuff", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_list_documents_after_upload(client):
    """After uploading, GET /documents should list the file."""
    client.post(
        "/upload",
        files={"file": ("notes.md", b"# Notes", "text/markdown")},
    )
    resp = client.get("/documents")
    assert resp.status_code == 200
    names = [d["name"] for d in resp.json()["documents"]]
    assert "notes.md" in names


def test_ingest_empty(client):
    """Ingest on an empty profile_docs dir should complete without error."""
    with patch("resumate.routes.documents.index_profile_docs", return_value=0):
        resp = client.post("/ingest")
    assert resp.status_code == 200
    assert resp.json()["chunks_indexed"] == 0
