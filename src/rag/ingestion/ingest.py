"""
ingest.py
Load and index profile documents or job descriptions into Chroma.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader

from rag.config.settings import PROFILE_DOC_DIR, RAG_DIR
from rag.ingestion.chunking.text_splitter import SPLITTER
from rag.utils.logging import timed_block
from rag.vectorstore.chroma_instance import get_vectordb

logger = logging.getLogger("rag")


def _normalize_jd_text(jd_text: str) -> str:
    return jd_text.replace("\r\n", "\n").replace("\r", "\n")


def load_docs_from(folder: Path, doc_type: str):
    """Load PDFs / text / markdown files from a folder and tag metadata."""
    docs = []
    for path in sorted(folder.glob("*")):
        if path.suffix.lower() == ".pdf":
            docs += PyPDFLoader(str(path)).load()
        elif path.suffix.lower() in {".txt", ".md"}:
            docs += TextLoader(str(path), encoding="utf-8").load()

    for doc in docs:
        doc.metadata["source"] = doc.metadata.get("source") or str(folder)
        doc.metadata["doc_type"] = doc_type
        doc.metadata["uid"] = str(uuid.uuid4())[:8]
    return docs


def _profile_state_path() -> Path:
    return RAG_DIR / ".profile_index_state.json"


def _profile_fingerprint() -> dict[str, float | int]:
    fingerprint: dict[str, float | int] = {}
    for path in sorted(PROFILE_DOC_DIR.glob("*")):
        if path.suffix.lower() not in {".pdf", ".txt", ".md"}:
            continue
        stat = path.stat()
        fingerprint[path.name] = int(stat.st_mtime_ns)
        fingerprint[f"{path.name}:size"] = int(stat.st_size)
    return fingerprint


def _profile_changed() -> bool:
    state_path = _profile_state_path()
    current = _profile_fingerprint()
    if not state_path.exists():
        return True
    try:
        previous = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return True
    return previous != current


def _save_profile_state() -> None:
    state_path = _profile_state_path()
    state_path.write_text(json.dumps(_profile_fingerprint(), indent=2), encoding="utf-8")


def _jd_state_path() -> Path:
    return RAG_DIR / ".jd_index_state.json"


def _jd_text_fingerprint(jd_text: str) -> str:
    return hashlib.sha256(_normalize_jd_text(jd_text).encode("utf-8")).hexdigest()


def index_profile_docs() -> int:
    """Index persistent profile documents (CVs, summaries)."""
    if not _profile_changed():
        return 0

    vectordb = get_vectordb()
    try:
        vectordb.delete(where={"doc_type": "profile"})
    except Exception:
        # Non-fatal: continue to avoid blocking generation on store-specific delete behavior.
        pass
    with timed_block("profile_load_docs"):
        docs = load_docs_from(PROFILE_DOC_DIR, "profile")
    with timed_block("profile_chunk"):
        chunks = SPLITTER.split_documents(docs)
    if chunks:
        with timed_block("profile_embed_add"):
            vectordb.add_documents(chunks)
    _save_profile_state()
    return len(chunks)


def index_jd_text(jd_text: str) -> int:
    """Index the current job description as a temporary doc."""
    tmp = RAG_DIR / "jd.txt"
    jd_norm = _normalize_jd_text(jd_text)
    fp = _jd_text_fingerprint(jd_text)
    state_path = _jd_state_path()

    previous: dict | None = None
    if state_path.exists():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            previous = None

    on_disk_matches = (
        tmp.exists() and _normalize_jd_text(tmp.read_text(encoding="utf-8")) == jd_norm
    )
    cache_hit = bool(
        previous is not None
        and previous.get("jd_sha256") == fp
        and on_disk_matches
    )
    if cache_hit:
        n_chunks = int(previous.get("chunk_count", 0))
        logger.info("[JD cache] HIT — skipping rebuild (chunks=%s)", n_chunks)
        return n_chunks

    if not state_path.exists():
        miss_reason = "no_state_file"
    elif previous is None:
        miss_reason = "state_unreadable"
    elif previous.get("jd_sha256") != fp:
        miss_reason = "jd_hash_changed"
    elif not tmp.exists():
        miss_reason = "jd.txt_missing"
    else:
        miss_reason = "jd.txt_content_mismatch"
    logger.info("[JD cache] MISS — rebuilding (%s)", miss_reason)

    tmp.write_text(jd_norm, encoding="utf-8")

    vectordb = get_vectordb()
    try:
        vectordb.delete(where={"doc_type": "jd"})
    except Exception:
        pass

    with timed_block("jd_load_docs"):
        docs = load_docs_from(RAG_DIR, "jd")
    docs = [d for d in docs if "jd.txt" in d.metadata.get("source", "")]
    with timed_block("jd_chunk"):
        chunks = SPLITTER.split_documents(docs)
    if chunks:
        with timed_block("jd_embed_add"):
            vectordb.add_documents(chunks)
    count = len(chunks)
    state_path.write_text(
        json.dumps({"jd_sha256": fp, "chunk_count": count}, indent=2),
        encoding="utf-8",
    )
    return count


__all__ = ["load_docs_from", "index_profile_docs", "index_jd_text"]
