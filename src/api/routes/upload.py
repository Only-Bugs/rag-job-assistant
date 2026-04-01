"""POST /upload, POST /ingest, GET /documents — document management endpoints."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from rag.config.settings import DEV_USER_ID, get_user_data_dir
from rag.ingestion.ingest import index_profile_docs

logger = logging.getLogger("api")
router = APIRouter()

_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md"}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

_USER_DATA_DIR = get_user_data_dir(DEV_USER_ID)


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)) -> dict:
    """Upload a resume document (.pdf / .txt / .md) into the user's profile_docs."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {ext!r}. Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )

    contents = await file.read()
    if len(contents) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    dest = _USER_DATA_DIR / "profile_docs" / (file.filename or "upload")
    dest.write_bytes(contents)
    logger.info("upload: saved %s (%d bytes) → %s", file.filename, len(contents), dest)
    return {"status": "uploaded", "filename": dest.name, "size_bytes": len(contents)}


@router.post("/ingest")
async def trigger_ingest() -> dict:
    """Re-index the user's profile_docs into their Chroma vector store.

    Runs in a thread executor because indexing is CPU-bound and blocking.
    Returns immediately if nothing has changed (fingerprint cache hit).
    """
    loop = asyncio.get_event_loop()
    chunks = await loop.run_in_executor(None, index_profile_docs, _USER_DATA_DIR)
    logger.info("ingest: %d chunks indexed for %s", chunks, DEV_USER_ID)
    return {"status": "done", "chunks_indexed": chunks}


@router.get("/documents")
async def list_documents() -> dict:
    """List documents currently in the user's profile_docs directory."""
    docs_dir = _USER_DATA_DIR / "profile_docs"
    if not docs_dir.exists():
        return {"documents": []}
    files = [
        {
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "type": f.suffix.lower(),
        }
        for f in sorted(docs_dir.iterdir())
        if f.is_file() and f.suffix.lower() in _ALLOWED_EXTENSIONS
    ]
    return {"documents": files}
