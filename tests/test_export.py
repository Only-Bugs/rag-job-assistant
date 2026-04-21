"""Tests for POST /export/pdf and POST /export/docx endpoints."""

from __future__ import annotations

_SAMPLE_CONTENT = {
    "content": {
        "skills": "## Skills\n- Python\n- **FastAPI**\n- Docker",
        "cover": "Dear Hiring Manager,\n\nI am writing to apply...",
        "emails": "### Email 1\nSubject: Application\n\nHi,",
        "ats": "Experienced developer with 5+ years...",
    }
}


def test_export_pdf(client):
    resp = client.post("/export/pdf", json=_SAMPLE_CONTENT)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:5] == b"%PDF-"


def test_export_docx(client):
    resp = client.post("/export/docx", json=_SAMPLE_CONTENT)
    assert resp.status_code == 200
    assert "wordprocessingml" in resp.headers["content-type"]
    # DOCX files are ZIP archives — starts with PK header
    assert resp.content[:2] == b"PK"


def test_export_empty_content(client):
    """Empty sections should not crash the export."""
    resp = client.post("/export/pdf", json={"content": {}})
    assert resp.status_code == 200
