"""Agentic tool endpoints: /tools/*"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from resumate.middleware.auth import get_current_user
from resumate.services.resume_parser import extract_text, parse_resume_text

logger = logging.getLogger("resumate")
router = APIRouter(prefix="/tools", tags=["tools"])

_ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/parse-resume")
async def parse_resume(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> dict:
    """Extract structured profile data from an uploaded resume file.

    Accepts PDF, DOCX, or TXT. Returns JSON with extracted fields:
    name, title, location, email, phone, links, skills, achievements, pitch.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {ext!r}. Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )

    contents = await file.read()
    if len(contents) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    raw_text = extract_text(contents, file.filename or "upload")
    if not raw_text.strip():
        raise HTTPException(status_code=422, detail="Could not extract any text from the file.")

    parsed = parse_resume_text(raw_text)
    logger.info("parse-resume: extracted %d fields from %s", len(parsed), file.filename)
    return parsed
