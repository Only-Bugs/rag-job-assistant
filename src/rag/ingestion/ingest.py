"""
ingest.py
Load and index profile documents or job descriptions into Chroma.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader, TextLoader

from rag.config.settings import PROFILE_DOC_DIR, RAG_DIR
from rag.ingestion.chunking.text_splitter import SPLITTER
from rag.vectorstore.chroma_instance import get_vectordb


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


def index_profile_docs() -> int:
    """Index persistent profile documents (CVs, summaries)."""
    vectordb = get_vectordb()
    docs = load_docs_from(PROFILE_DOC_DIR, "profile")
    chunks = SPLITTER.split_documents(docs)
    if chunks:
        vectordb.add_documents(chunks)
    return len(chunks)


def index_jd_text(jd_text: str) -> int:
    """Index the current job description as a temporary doc."""
    tmp = RAG_DIR / "jd.txt"
    tmp.write_text(jd_text, encoding="utf-8")

    docs = load_docs_from(RAG_DIR, "jd")
    docs = [d for d in docs if "jd.txt" in d.metadata.get("source", "")]
    chunks = SPLITTER.split_documents(docs)

    vectordb = get_vectordb()
    if chunks:
        vectordb.add_documents(chunks)
    return len(chunks)


__all__ = ["load_docs_from", "index_profile_docs", "index_jd_text"]
