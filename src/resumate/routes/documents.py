"""POST /upload, POST /ingest, GET /documents -- document management endpoints."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from resumate.middleware.auth import get_current_user
from resumate.config.settings import get_user_data_dir
from resumate.services.ingestion import index_profile_docs

logger = logging.getLogger("resumate")
router = APIRouter()

_ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> dict:
    """Upload a resume document (.pdf / .txt / .md / .docx) into the user's profile_docs."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type {ext!r}. Allowed: {sorted(_ALLOWED_EXTENSIONS)}",
        )

    contents = await file.read()
    if len(contents) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    user_data_dir = get_user_data_dir(user["user_id"])
    dest = user_data_dir / "profile_docs" / (file.filename or "upload")
    dest.write_bytes(contents)
    logger.info("upload: saved %s (%d bytes) -> %s", file.filename, len(contents), dest)
    return {"status": "uploaded", "filename": dest.name, "size_bytes": len(contents)}


@router.post("/ingest")
async def trigger_ingest(user: dict = Depends(get_current_user)) -> dict:
    """Re-index the user's profile_docs into their Chroma vector store."""
    user_data_dir = get_user_data_dir(user["user_id"])
    loop = asyncio.get_event_loop()
    chunks = await loop.run_in_executor(None, index_profile_docs, user_data_dir)
    logger.info("ingest: %d chunks indexed for %s", chunks, user["user_id"])
    return {"status": "done", "chunks_indexed": chunks}


@router.get("/documents")
async def list_documents(user: dict = Depends(get_current_user)) -> dict:
    """List documents currently in the user's profile_docs directory."""
    docs_dir = get_user_data_dir(user["user_id"]) / "profile_docs"
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


@router.delete("/documents/{filename}")
async def delete_document(
    filename: str,
    user: dict = Depends(get_current_user),
) -> dict:
    """Delete a document from the user's profile_docs and re-index."""
    docs_dir = get_user_data_dir(user["user_id"]) / "profile_docs"
    target = docs_dir / filename

    # Prevent path traversal
    if not target.resolve().parent == docs_dir.resolve():
        raise HTTPException(status_code=400, detail="Invalid filename")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Document not found")

    target.unlink()
    logger.info("delete: removed %s for %s", filename, user["user_id"])

    # Re-index after deletion
    user_data_dir = get_user_data_dir(user["user_id"])
    loop = asyncio.get_event_loop()
    chunks = await loop.run_in_executor(None, index_profile_docs, user_data_dir)

    return {"status": "deleted", "filename": filename, "chunks_reindexed": chunks}
